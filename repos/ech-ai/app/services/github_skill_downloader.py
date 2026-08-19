"""从GitHub链接下载Agent Skill目录。

支持如下URL格式：
    https://github.com/{owner}/{repo}/tree/{ref}/{path}
    https://github.com/{owner}/{repo}/blob/{ref}/{path}

下载器通过 raw.githubusercontent.com 获取文件内容，
利用GitHub网页JSON接口（``?json=1``）获取目录列表。
两者均无需API Token，规避官方REST API匿名访问每小时60次的严格限流。
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import httpx
import yaml

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量 / 安全限制
# ---------------------------------------------------------------------------

_MAX_FILES = 100
_MAX_FILE_SIZE = 1 * 1024 * 1024  # 单个文件最大1MB
_RAW_BASE = "https://raw.githubusercontent.com"
_REQUEST_TIMEOUT = 30.0  # 秒

# 解析GitHub tree/blob链接正则
# 匹配：https://github.com/{owner}/{repo}/(tree|blob)/{ref}/{path...}
_GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[^/]+)/"
    r"(?P<repo>[^/]+)/"
    r"(?:tree|blob)/"
    r"(?P<ref>[^/]+)/"
    r"(?P<path>.+?)/?$"
)


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------


class GitHubURLParseError(Exception):
    """GitHub URL格式解析失败时抛出。"""


class GitHubDownloadError(Exception):
    """GitHub资源下载过程异常。"""


class SkillValidationError(Exception):
    """下载得到的Skill校验不通过。"""


# ---------------------------------------------------------------------------
# 下载器实现
# ---------------------------------------------------------------------------


class GitHubSkillDownloader:
    """从GitHub拉取Agent Skill目录到本地磁盘。

    使用 raw.githubusercontent.com 下载文件，网页JSON接口获取目录列表，**不需要API Token**。
    """

    # ------------------------------------------------------------------
    # URL解析
    # ------------------------------------------------------------------

    @staticmethod
    def parse_github_url(url: str) -> tuple[str, str, str, str]:
        """解析GitHub tree/blob链接，返回 (owner, repo, ref, dir_path)。

        支持：
        - ``/tree/{ref}/{path}`` — 标准目录链接
        - ``/blob/{ref}/{path}`` — 用户复制的文件页面链接
        - URL末尾直接指向SKILL.md等文件：自动截取其父目录作为Skill根目录

        Raises:
            GitHubURLParseError: URL格式不匹配预期模板。
        """
        url = url.strip()
        match = _GITHUB_URL_RE.match(url)
        if not match:
            raise GitHubURLParseError(
                f"无效GitHub链接：'{url}'。"
                "期望格式：https://github.com/owner/repo/tree/branch/path"
            )

        owner = match.group("owner")
        repo = match.group("repo")
        ref = match.group("ref")
        path = match.group("path").rstrip("/")

        # 如果path指向文件（带后缀），取父目录作为skill根目录
        filename_part = path.rsplit("/", 1)[-1]
        if "." in filename_part:
            if "/" not in path:
                raise GitHubURLParseError(
                    f"无法从链接 '{url}' 解析Skill目录：该路径指向仓库根目录下的单个文件。"
                )
            path = path.rsplit("/", 1)[0]

        return owner, repo, ref, path

    # ------------------------------------------------------------------
    # 对外公开接口
    # ------------------------------------------------------------------

    async def download_skill(
        self,
        github_url: str,
        target_dir: Path,
        github_token: Optional[str] = None,
    ) -> str:
        """从GitHub下载Skill目录到目标路径target_dir。

        先下载到临时目录做校验，校验通过后原子移动到目标目录，保证写入原子性。

        Args:
            github_url: 指向Skill目录的GitHub链接
            target_dir: Skill本地存放目录
            github_token: 可选token，当前未实际使用，仅为兼容预留

        Returns:
            从SKILL.md前置元数据解析得到的skill名称

        Raises:
            GitHubURLParseError: URL格式错误
            GitHubDownloadError: 网络或下载失败
            SkillValidationError: SKILL.md缺失或格式非法
        """
        owner, repo, ref, path = self.parse_github_url(github_url)

        logger.info(
            "开始从GitHub下载Skill: %s/%s ref=%s path=%s",
            owner, repo, ref, path,
        )

        tmp_root = Path(tempfile.mkdtemp(prefix="skill_import_"))
        try:
            await self._fetch_directory(
                owner=owner,
                repo=repo,
                ref=ref,
                remote_path=path,
                local_dir=tmp_root,
                file_count=0,
            )

            # 校验SKILL.md并读取skill名称
            skill_name = self._validate_skill_md(tmp_root)

            # 原子迁移到目标目录
            if target_dir.exists():
                shutil.rmtree(target_dir)
            target_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp_root), str(target_dir))

            logger.info("Skill '%s' 导入成功，目标路径：%s", skill_name, target_dir)
            return skill_name

        except Exception:
            # 异常场景清理临时目录
            shutil.rmtree(tmp_root, ignore_errors=True)
            raise

    # ------------------------------------------------------------------
    # 内部工具：通过网页JSON接口递归拉取目录
    # ------------------------------------------------------------------

    async def _fetch_directory(
        self,
        owner: str,
        repo: str,
        ref: str,
        remote_path: str,
        local_dir: Path,
        file_count: int,
    ) -> int:
        """递归拉取GitHub目录。

        网页JSON接口获取目录列表，raw.githubusercontent.com下载文件，均无需token。
        返回累计文件数，用于执行文件数量上限校验。
        """
        items = await self._web_list_directory(owner, repo, ref, remote_path)

        for item in items:
            content_type = item.get("contentType", "")
            item_name = item.get("name", "")

            if not item_name:
                continue

            if file_count >= _MAX_FILES:
                raise GitHubDownloadError(
                    f"Skill文件数量超过上限 {_MAX_FILES}"
                )

            if content_type == "file":
                file_path = f"{remote_path}/{item_name}"
                raw_url = f"{_RAW_BASE}/{owner}/{repo}/{ref}/{file_path}"

                target_path = local_dir / item_name
                await self._download_file(raw_url, target_path)
                file_count += 1

            elif content_type == "directory":
                sub_dir = local_dir / item_name
                sub_dir.mkdir(parents=True, exist_ok=True)
                sub_remote_path = f"{remote_path}/{item_name}"
                file_count = await self._fetch_directory(
                    owner=owner,
                    repo=repo,
                    ref=ref,
                    remote_path=sub_remote_path,
                    local_dir=sub_dir,
                    file_count=file_count,
                )

        return file_count

    async def _web_list_directory(
        self,
        owner: str,
        repo: str,
        ref: str,
        path: str,
    ) -> list[dict]:
        """调用GitHub网页JSON接口获取目录内容。

        请求 ``https://github.com/{owner}/{repo}/tree/{ref}/{path}?json=1``
        返回包含 items 数组的JSON，**不计入REST API限流，无需鉴权**。
        """
        url = f"https://github.com/{owner}/{repo}/tree/{ref}/{path}"
        headers = {
            "Accept": "application/json",
            "User‑Agent": "Mozilla/5.0 (compatible; TGO‑Skill‑Importer/1.0)",
            "X‑Requested‑With": "XMLHttpRequest",
        }

        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT, follow_redirects=True
        ) as client:
            resp = await client.get(url, headers=headers, params={"json": "1"})

        if resp.status_code == 404:
            raise GitHubDownloadError(
                f"GitHub路径不存在: {owner}/{repo}/{path} (ref={ref})。"
                "请检查链接、仓库与分支是否有效。"
            )
        if resp.status_code != 200:
            raise GitHubDownloadError(
                f"获取目录列表HTTP {resp.status_code}，仓库：{owner}/{repo}/{path}。响应片段：{resp.text[:300]}"
            )

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise GitHubDownloadError(
                f"解析GitHub目录JSON响应失败 {owner}/{repo}/{path}: {exc}"
            ) from exc

        # JSON结构：payload → tree → items
        payload = data.get("payload", {})
        tree = payload.get("tree", {})
        items: list[dict] = tree.get("items", [])

        if not items:
            raise GitHubDownloadError(
                f"目录为空或不是合法目录：{owner}/{repo}/{path} (ref={ref})"
            )

        return items

    # ------------------------------------------------------------------
    # 内部工具：raw.githubusercontent.com下载单个文件
    # ------------------------------------------------------------------

    async def _download_file(
        self,
        raw_url: str,
        target_path: Path,
    ) -> None:
        """从raw.githubusercontent.com下载单个公开仓库文件。无需鉴权。"""
        async with httpx.AsyncClient(
            timeout=_REQUEST_TIMEOUT, follow_redirects=True
        ) as client:
            resp = await client.get(raw_url)

        if resp.status_code == 404:
            raise GitHubDownloadError(f"文件不存在：{raw_url}")
        if resp.status_code != 200:
            raise GitHubDownloadError(f"下载失败 {raw_url}: HTTP {resp.status_code}")

        # 文件大小防护
        if len(resp.content) > _MAX_FILE_SIZE:
            logger.warning(
                "跳过超大文件 %s（%d字节 > 上限%d字节）",
                target_path.name, len(resp.content), _MAX_FILE_SIZE,
            )
            return

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(resp.content)

    # ------------------------------------------------------------------
    # Skill校验逻辑
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_skill_md(skill_dir: Path) -> str:
        """校验SKILL.md存在性与YAML前置元数据，返回skill名称。

        Raises:
            SkillValidationError: 任意校验项不满足时抛出
        """
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            raise SkillValidationError(
                "下载目录缺少SKILL.md文件。合法Skill必须携带带YAML前置元数据的SKILL.md。"
            )

        text = skill_md.read_text(encoding="utf‑8")

        if not text.startswith("---"):
            raise SkillValidationError(
                "SKILL.md缺失YAML前置元数据，文件开头必须为 '---'。"
            )

        parts = text.split("---", 2)
        if len(parts) < 3:
            raise SkillValidationError("SKILL.md的YAML前置元数据格式损坏。")

        try:
            fm: dict = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError as exc:
            raise SkillValidationError(
                f"SKILL.md前置元数据YAML解析错误：{exc}"
            ) from exc

        name = fm.get("name")
        if not name or not isinstance(name, str):
            raise SkillValidationError(
                "SKILL.md前置元数据缺少必填的name字段。"
            )

        description = fm.get("description")
        if not description or not isinstance(description, str):
            raise SkillValidationError(
                "SKILL.md前置元数据缺少必填的description字段。"
            )

        # skill名称格式校验：小写字母、数字、短横线；首尾不能是横线，禁止连续横线；允许数字开头（例如"1password"）
        name_re = re.compile(r"^[a‑z0‑9][a‑z0‑9‑]*[a‑z0‑9]$")
        if len(name) < 2 or len(name) > 64:
            raise SkillValidationError(
                f"Skill名称长度必须2‑64字符，实际 '{name}'（{len(name)}字符）。"
            )
        if not name_re.match(name):
            raise SkillValidationError(
                f"Skill名称 '{name}' 非法：仅允许小写字母、数字、短横线，不能首尾为短横线。"
            )
        if "--" in name:
            raise SkillValidationError(
                f"Skill名称 '{name}' 包含连续短横线，不允许。"
            )

        # 将非标准元数据迁移到metadata，避免Agno运行时严格校验报错
        _STANDARD_FIELDS = {
            "name", "description", "license",
            "allowed‑tools", "compatibility", "metadata",
        }
        extra_keys = [k for k in fm if k not in _STANDARD_FIELDS]
        if extra_keys:
            meta = fm.get("metadata") or {}
            for k in extra_keys:
                meta[k] = fm.pop(k)
            fm["metadata"] = meta

            # 重写清洗后的SKILL.md到磁盘
            body = parts[2]
            fm_str = yaml.dump(
                fm, default_flow_style=False,
                allow_unicode=True, sort_keys=False,
            ).rstrip("\n")
            skill_md.write_text(
                f"---\n{fm_str}\n---\n{body}",
                encoding="utf‑8",
            )
            logger.info(
                "将非标准前置元数据字段 %s 迁移至skill '%s' 的metadata",
                extra_keys, name,
            )

        return name