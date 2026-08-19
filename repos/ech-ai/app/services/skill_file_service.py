"""File‑system‑based skill CRUD service.
基于文件系统实现Skill的增删改查服务。
每个Skill对应一个文件夹，文件夹内必须包含 SKILL.md 文件（YAML前置元数据+Markdown正文），
还可以可选携带 scripts/、references/ 两个子目录。

目录布局：
    {base_dir}/
    ├── _official/          # 全局官方Skill目录，所有项目共享，只读不可修改
    │   └── code‑review/
    │       └── SKILL.md
    ├── {project_id}/       # 项目私有Skill，每个项目独立隔离
    │   └── my‑skill/
    │       ├── SKILL.md
    │       ├── scripts/
    │       └── references/
    └── ...
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml

# Pydantic数据模型：Skill创建/更新请求、摘要、详情响应结构体
from app.schemas.skill import (
    SkillCreateRequest,
    SkillDetail,
    SkillSummary,
    SkillUpdateRequest,
)

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 自定义业务异常
# ---------------------------------------------------------------------------


class SkillNotFoundError(Exception):
    """请求的Skill目录不存在时抛出"""


class SkillConflictError(Exception):
    """创建Skill，同名目录已存在，冲突抛出"""


class SkillReadOnlyError(Exception):
    """尝试修改/删除官方只读Skill(_official目录下)抛出"""


class SkillPathTraversalError(Exception):
    """路径校验检测到路径穿越攻击（../ 等）抛出"""


# ---------------------------------------------------------------------------
# Skill名称合法性校验
# ---------------------------------------------------------------------------

# Skill名称正则：小写字母数字开头结尾，中间允许单个短横线
_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9‑]*[a‑z0‑9]$")
_MAX_SKILL_NAME_LEN = 64


def _validate_skill_name(name: str) -> str:
    """校验skill名称是否符合命名规范
    规则：小写字母、数字、单个短横线；长度2‑64；不能连续横线；首尾不能是横线。

    :param name: 待校验skill名称
    :return: 校验通过后的名称
    :raises ValueError: 名称非法
    """
    if len(name) < 2 or len(name) > _MAX_SKILL_NAME_LEN:
        raise ValueError(
            f"Skill name must be 2‑{_MAX_SKILL_NAME_LEN} characters, got {len(name)}"
        )
    if not _SKILL_NAME_RE.match(name):
        raise ValueError(
            f"Invalid skill name '{name}': must be lowercase letters, digits, "
            "and single hyphens (no leading/trailing hyphens)"
        )
    if "--" in name:
        raise ValueError("Consecutive hyphens are not allowed in skill names")
    return name


# ---------------------------------------------------------------------------
# SKILL.md 文件解析 / 序列化工具函数
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析SKILL.md文件，拆分YAML前置元数据和markdown正文。
    文件开头以 --- 作为分隔符。没有前置元数据时返回空字典+全文本。

    :param text: SKILL.md完整文本
    :return: (yaml元数据字典, markdown正文)
    """
    if not text.startswith("---"):
        return {}, text

    # 最多分割2次，取出前后两个---中间的yaml内容
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    try:
        fm: dict = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        # yaml解析失败，元数据置空，不直接报错，保证文件还能读正文
        fm = {}

    body = parts[2].lstrip("\n")
    return fm, body


def _serialize_skill_md(
    fm: dict,
    body: str,
) -> str:
    """将元数据字典 + markdown正文序列化为SKILL.md完整文本。
    sort_keys=False 保持yaml字段顺序，allow_unicode支持中文。
    """
    fm_str = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).rstrip("\n")
    return f"---\n{fm_str}\n---\n\n{body}\n"


# ---------------------------------------------------------------------------
# SkillFileService 主服务类：全部基于本地文件系统操作，无数据库
# ---------------------------------------------------------------------------


class SkillFileService:
    """基于文件系统的Skill CRUD服务。
    注意：本服务全部操作本地磁盘，**不是数据库**；
    区分「项目私有skill」和「全局官方只读skill」；
    做严格路径校验防御路径穿越漏洞。
    """

    def __init__(self, base_dir: str) -> None:
        """
        :param base_dir: skill存储根目录路径
        """
        self.base_dir = Path(base_dir)
        # 全局官方skill目录，所有项目共享，只读
        self.official_dir = self.base_dir / "_official"

    # ------------------------------------------------------------------
    # 路径内部工具方法
    # ------------------------------------------------------------------

    def _project_dir(self, project_id: str) -> Path:
        """返回指定项目的skill根目录路径"""
        return self.base_dir / project_id

    def _skill_dir(self, project_id: str, skill_name: str) -> Path:
        """获取【项目私有skill】目录路径，同时做路径穿越安全校验。
        仅用于创建、更新、删除项目私有skill；**不会去查找official目录**。
        """
        safe_name = _validate_skill_name(skill_name)
        path = self._project_dir(project_id) / safe_name
        # 安全校验：解析绝对路径，必须落在base_dir内部，防止../逃逸
        try:
            resolved = path.resolve()
            base_resolved = self.base_dir.resolve()
            if not str(resolved).startswith(str(base_resolved)):
                raise SkillPathTraversalError(f"Path traversal detected: {skill_name}")
        except (OSError, ValueError) as exc:
            raise SkillPathTraversalError(f"Invalid path: {exc}") from exc
        return path

    def _resolve_skill_dir(self, project_id: str, skill_name: str) -> Path:
        """查找skill真实目录：优先找项目私有；找不到再去 _official 全局目录查找。
        读操作统一用这个方法；写操作不能用，因为official只读。
        :raises SkillNotFoundError: 两边都找不到skill
        """
        safe_name = _validate_skill_name(skill_name)
        project_path = self._project_dir(project_id) / safe_name
        if project_path.exists() and project_path.is_dir():
            return project_path
        official_path = self.official_dir / safe_name
        if official_path.exists() and official_path.is_dir():
            return official_path
        raise SkillNotFoundError(f"Skill '{skill_name}' not found")

    def _is_official(self, skill_dir: Path) -> bool:
        """判断该skill目录是否属于官方只读 _official 目录"""
        try:
            return str(skill_dir.resolve()).startswith(str(self.official_dir.resolve()))
        except (OSError, ValueError):
            return False

    # ------------------------------------------------------------------
    # Skill启用/禁用状态管理（每个项目独立配置 .disabled_skills.json）
    # ------------------------------------------------------------------

    _DISABLED_FILE = ".disabled_skills.json"

    def _disabled_file_path(self, project_id: str) -> Path:
        """返回某个项目的禁用skill配置文件路径"""
        return self._project_dir(project_id) / self._DISABLED_FILE

    def _load_disabled_skills(self, project_id: str) -> Set[str]:
        """加载项目被禁用的skill名称集合。文件不存在返回空集合。"""
        path = self._disabled_file_path(project_id)
        if not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf‑8"))
            if isinstance(data, list):
                return set(data)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cannot read disabled skills file %s: %s", path, exc)
        return set()

    def _save_disabled_skills(self, project_id: str, disabled: Set[str]) -> None:
        """持久化保存项目禁用skill集合到json文件"""
        path = self._disabled_file_path(project_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(sorted(disabled), ensure_ascii=False, indent=2),
            encoding="utf‑8",
        )

    async def toggle_skill(
        self, project_id: str, skill_name: str, enabled: bool
    ) -> bool:
        """开启/关闭项目下某个skill。官方skill也可以被项目禁用。
        :param project_id: 项目ID
        :param skill_name: skill名称
        :param enabled: True启用，False禁用
        :return: 返回设置后的enabled状态
        """
        # 先校验skill确实存在（私有或官方）
        _validate_skill_name(skill_name)
        self._resolve_skill_dir(project_id, skill_name)

        disabled = self._load_disabled_skills(project_id)
        if enabled:
            disabled.discard(skill_name)
        else:
            disabled.add(skill_name)
        self._save_disabled_skills(project_id, disabled)
        return enabled

    def get_disabled_skills(self, project_id: str) -> Set[str]:
        """对外接口：获取项目当前禁用的skill集合"""
        return self._load_disabled_skills(project_id)

    # ------------------------------------------------------------------
    # Skill主CRUD接口
    # ------------------------------------------------------------------

    async def list_skills(self, project_id: str) -> List[SkillSummary]:
        """列出该项目可见全部skill：项目私有skill + 全局official skill。
        同时读取项目禁用配置，填充每个skill的enabled状态。
        """
        skills: List[SkillSummary] = []
        disabled = self._load_disabled_skills(project_id)

        # 1. 加载项目私有skill
        project_dir = self._project_dir(project_id)
        if project_dir.exists():
            for child in sorted(project_dir.iterdir()):
                # 必须是文件夹，并且内部存在SKILL.md才算合法skill
                if child.is_dir() and (child / "SKILL.md").exists():
                    summary = self._parse_skill_summary(child, is_official=False)
                    if summary is not None:
                        summary.enabled = child.name not in disabled
                        skills.append(summary)

        # 2. 加载全局官方skill
        if self.official_dir.exists():
            for child in sorted(self.official_dir.iterdir()):
                if child.is_dir() and (child / "SKILL.md").exists():
                    summary = self._parse_skill_summary(child, is_official=True)
                    if summary is not None:
                        summary.enabled = child.name not in disabled
                        skills.append(summary)

        return skills

    async def get_skill(self, project_id: str, skill_name: str) -> SkillDetail:
        """读取skill完整详情：元数据、指令正文、scripts/references文件列表"""
        skill_dir = self._resolve_skill_dir(project_id, skill_name)
        return self._parse_skill_detail(skill_dir)

    async def create_skill(
        self, project_id: str, data: SkillCreateRequest
    ) -> SkillDetail:
        """创建项目私有skill，新建目录，写入SKILL.md，可选写入scripts/references子文件。
        official目录不能通过此接口创建。
        """
        skill_dir = self._skill_dir(project_id, data.name)
        if skill_dir.exists():
            raise SkillConflictError(f"Skill '{data.name}' already exists")

        # 创建skill根文件夹
        skill_dir.mkdir(parents=True, exist_ok=False)

        # 写入SKILL.md主文件
        self._write_skill_md(skill_dir, data)

        # 可选写入scripts目录下文件
        if data.scripts:
            self._write_files(skill_dir / "scripts", data.scripts)
        # 可选写入references目录下文件
        if data.references:
            self._write_files(skill_dir / "references", data.references)

        return self._parse_skill_detail(skill_dir)

    async def update_skill(
        self, project_id: str, skill_name: str, data: SkillUpdateRequest
    ) -> SkillDetail:
        """更新skill的SKILL.md元数据与正文。官方skill禁止修改。
        merge=True：保留旧的yaml元数据，只覆盖传入的字段。
        """
        skill_dir = self._resolve_skill_dir(project_id, skill_name)

        if self._is_official(skill_dir):
            raise SkillReadOnlyError(
                f"Cannot modify official skill '{skill_name}'"
            )

        # merge模式更新SKILL.md
        self._write_skill_md(skill_dir, data, merge=True)
        return self._parse_skill_detail(skill_dir)

    async def delete_skill(self, project_id: str, skill_name: str) -> None:
        """完整删除项目私有skill整个目录。官方skill禁止删除。"""
        skill_dir = self._skill_dir(project_id, skill_name)
        if not skill_dir.exists():
            raise SkillNotFoundError(f"Skill '{skill_name}' not found")

        if self._is_official(skill_dir):
            raise SkillReadOnlyError(
                f"Cannot delete official skill '{skill_name}'"
            )

        # 递归删除整个skill文件夹
        shutil.rmtree(skill_dir)

    # ------------------------------------------------------------------
    # Skill内部子文件CRUD（scripts / references下的单个文件读写删）
    # ------------------------------------------------------------------

    async def get_file(
        self, project_id: str, skill_name: str, file_path: str
    ) -> str:
        """读取skill内部任意子文件文本内容（scripts / references）。
        做路径校验，禁止跳出skill目录。
        """
        skill_dir = self._resolve_skill_dir(project_id, skill_name)
        target = (skill_dir / file_path).resolve()
        # 安全校验：目标文件必须落在skill_dir内部
        if not str(target).startswith(str(skill_dir.resolve())):
            raise SkillPathTraversalError(f"Invalid file path: {file_path}")
        if not target.is_file():
            raise SkillNotFoundError(
                f"File '{file_path}' not found in skill '{skill_name}'"
            )
        return target.read_text(encoding="utf‑8")

    async def put_file(
        self,
        project_id: str,
        skill_name: str,
        file_path: str,
        content: str,
    ) -> None:
        """创建/更新skill内部子文件；官方skill禁止修改。"""
        skill_dir = self._resolve_skill_dir(project_id, skill_name)

        if self._is_official(skill_dir):
            raise SkillReadOnlyError(
                f"Cannot modify files in official skill '{skill_name}'"
            )

        target = (skill_dir / file_path).resolve()
        if not str(target).startswith(str(skill_dir.resolve())):
            raise SkillPathTraversalError(f"Invalid file path: {file_path}")

        # 父目录不存在自动创建
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf‑8")

    async def delete_file(
        self, project_id: str, skill_name: str, file_path: str
    ) -> None:
        """删除skill内部某个子文件；官方skill禁止操作。"""
        skill_dir = self._resolve_skill_dir(project_id, skill_name)

        if self._is_official(skill_dir):
            raise SkillReadOnlyError(
                f"Cannot delete files in official skill '{skill_name}'"
            )

        target = (skill_dir / file_path).resolve()
        if not str(target).startswith(str(skill_dir.resolve())):
            raise SkillPathTraversalError(f"Invalid file path: {file_path}")
        if not target.is_file():
            raise SkillNotFoundError(
                f"File '{file_path}' not found in skill '{skill_name}'"
            )
        target.unlink()

    # ------------------------------------------------------------------
    # 内部解析工具：把磁盘文件解析为Pydantic模型对象
    # ------------------------------------------------------------------

    def _parse_skill_summary(
        self, skill_dir: Path, *, is_official: bool
    ) -> Optional[SkillSummary]:
        """解析SKILL.md，输出SkillSummary摘要对象；读取出错返回None不抛异常。
        updated_at取自SKILL.md文件的修改时间（UTC时区）。
        """
        skill_md = skill_dir / "SKILL.md"
        try:
            text = skill_md.read_text(encoding="utf‑8")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", skill_md, exc)
            return None

        fm, _ = _parse_frontmatter(text)
        meta = fm.get("metadata") or {}

        # 获取文件修改时间，转UTC datetime
        try:
            stat = skill_md.stat()
            updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        except OSError:
            updated_at = None

        return SkillSummary(
            name=fm.get("name", skill_dir.name),
            description=fm.get("description", ""),
            author=meta.get("author"),
            is_official=is_official,
            is_featured=meta.get("is_featured", False),
            tags=meta.get("tags", []),
            updated_at=updated_at,
        )

    def _parse_skill_detail(self, skill_dir: Path) -> SkillDetail:
        """完整解析skill：yaml元数据 + markdown指令正文 + scripts/references文件清单。
        :raises SkillNotFoundError: SKILL.md读取失败
        """
        skill_md = skill_dir / "SKILL.md"
        try:
            text = skill_md.read_text(encoding="utf‑8")
        except OSError as exc:
            raise SkillNotFoundError(
                f"Cannot read SKILL.md in '{skill_dir.name}': {exc}"
            ) from exc

        fm, body = _parse_frontmatter(text)
        meta = fm.get("metadata") or {}

        try:
            stat = skill_md.stat()
            updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        except OSError:
            updated_at = None

        is_official = self._is_official(skill_dir)

        # 递归扫描scripts、references目录下所有文件，返回相对路径列表
        scripts = self._list_relative_files(skill_dir / "scripts")
        references = self._list_relative_files(skill_dir / "references")

        return SkillDetail(
            name=fm.get("name", skill_dir.name),
            description=fm.get("description", ""),
            author=meta.get("author"),
            is_official=is_official,
            is_featured=meta.get("is_featured", False),
            tags=meta.get("tags", []),
            updated_at=updated_at,
            instructions=body,
            license=fm.get("license"),
            version=meta.get("version"),
            # 过滤掉已经单独提取的元数据字段，剩下的放入metadata字典
            metadata={k: str(v) for k, v in meta.items() if k not in ("author", "version", "tags", "is_featured")},
            scripts=scripts,
            references=references,
        )

    # ------------------------------------------------------------------
    # 内部写文件工具
    # ------------------------------------------------------------------

    def _write_skill_md(
        self,
        skill_dir: Path,
        data: SkillCreateRequest | SkillUpdateRequest,
        *,
        merge: bool = False,
    ) -> None:
        """写入SKILL.md文件。
        merge=False：新建，fm清空；
        merge=True：更新，读取旧文件，保留原有yaml字段，只覆盖传入的字段。
        """
        skill_md = skill_dir / "SKILL.md"

        if merge and skill_md.exists():
            existing_text = skill_md.read_text(encoding="utf‑8")
            fm, body = _parse_frontmatter(existing_text)
        else:
            fm = {}
            body = ""

        # 覆盖顶层yaml字段
        if hasattr(data, "name") and getattr(data, "name", None) is not None:
            fm["name"] = data.name
        if data.description is not None:
            fm["description"] = data.description
        if hasattr(data, "license") and getattr(data, "license", None) is not None:
            fm["license"] = data.license

        # 更新metadata子字典
        meta = fm.get("metadata") or {}
        if hasattr(data, "author") and getattr(data, "author", None) is not None:
            meta["author"] = data.author
        if data.tags is not None:
            meta["tags"] = data.tags
        if hasattr(data, "is_featured") and getattr(data, "is_featured", None) is not None:
            meta["is_featured"] = data.is_featured
        if hasattr(data, "metadata") and getattr(data, "metadata", None) is not None:
            for k, v in data.metadata.items():
                meta[k] = v
        if meta:
            fm["metadata"] = meta

        # 更新markdown指令正文
        if data.instructions is not None:
            body = data.instructions

        skill_md.write_text(
            _serialize_skill_md(fm, body),
            encoding="utf‑8",
        )

    @staticmethod
    def _write_files(parent_dir: Path, files: Dict[str, str]) -> None:
        """批量写入一组文件到指定目录；key=文件名，value=文件文本内容。"""
        parent_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in files.items():
            safe = Path(filename).name
            (parent_dir / safe).write_text(content, encoding="utf‑8")

    @staticmethod
    def _list_relative_files(directory: Path) -> List[str]:
        """递归扫描目录，返回所有文件的相对路径字符串列表；目录不存在返回空列表。"""
        if not directory.exists() or not directory.is_dir():
            return []
        result: List[str] = []
        for root, _dirs, files in os.walk(directory):
            for f in sorted(files):
                full = Path(root) / f
                rel = full.relative_to(directory.parent)
                result.append(str(rel))
        return sorted(result)