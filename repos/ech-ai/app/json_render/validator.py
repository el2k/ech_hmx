"""Validation for json‑render SpecStream patch lines.
json‑render SpecStream 补丁行校验器
实现两层校验：轻量业务逻辑校验 + 可选 jsonschema 完整模式校验
遵循 RFC6902 JSON‑Patch 规范，对每一条patch做字段、op操作、必填项检查
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger

logger = get_logger(__name__)

# 当前模块所在目录，用于加载本地json schema文件
_MODULE_DIR = Path(__file__).resolve().parent
_SCHEMA_PATH = _MODULE_DIR / "schema" / "spec_stream_line.json"

# RFC6902 标准允许的op操作集合
_ALLOWED_OPS = {"add", "remove", "replace", "move", "copy", "test"}

# 可选依赖 jsonschema：没有安装则关闭schema强校验，仅保留轻量逻辑校验
try:
    import jsonschema

    _HAS_JSONSCHEMA = True
except ImportError:
    _HAS_JSONSCHEMA = False
    logger.warning("jsonschema package not installed; json‑render schema validation disabled")


class JsonRenderPatchValidator:
    """对 json‑render SpecStream 的每一条patch补丁做合法性校验
    校验分层：
        1. 轻量级硬编码校验：op白名单、path格式、各op对应的必填字段；始终执行
        2. jsonschema校验：依赖jsonschema库与schema文件，可选，缺失则跳过
    """

    def __init__(self, schema_path: Optional[Path] = None) -> None:
        """
        :param schema_path: 自定义schema json文件路径；不传使用内置默认路径
        """
        self._schema: Optional[Dict[str, Any]] = None
        path = schema_path or _SCHEMA_PATH
        # 如果schema文件存在，加载schema定义；文件不存在则schema置None，跳过schema校验
        if path.exists():
            self._schema = json.loads(path.read_text(encoding="utf-8"))

    def validate(self, patches: List[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
        """
        对外校验入口，批量校验patch补丁列表
        :param patches: 解析得到的patch字典数组
        :return: (is_valid: bool, error_msg: Optional[str])
                 is_valid=True全部合法；False时返回拼接后的错误摘要（最多前4条错误）
        """
        errors: List[str] = []

        for idx, patch in enumerate(patches):
            op = patch.get("op")
            path = patch.get("path")

            # 校验op：必须是字符串，且在允许操作白名单内
            if not isinstance(op, str) or op not in _ALLOWED_OPS:
                errors.append(f"patch[{idx}].op must be one of {sorted(_ALLOWED_OPS)}")
                continue

            # 校验path：JSON Pointer，字符串且必须以 / 开头
            if not isinstance(path, str) or not path.startswith("/"):
                errors.append(f"patch[{idx}].path must be a JSON Pointer path")

            # add / replace / test 操作必须携带 value 字段
            if op in {"add", "replace", "test"} and "value" not in patch:
                errors.append(f"patch[{idx}] missing required field 'value' for op={op}")

            # move / copy 操作必须携带 from 源指针字段
            if op in {"move", "copy"} and not isinstance(patch.get("from"), str):
                errors.append(f"patch[{idx}] missing required field 'from' for op={op}")

            # 条件触发：库已安装 + schema已加载，则执行jsonschema完整校验
            if _HAS_JSONSCHEMA and self._schema is not None:
                try:
                    jsonschema.validate(instance=patch, schema=self._schema)
                except jsonschema.ValidationError as exc:
                    errors.append(f"patch[{idx}]: {exc.message}")

        # 存在错误：截取最多前4条拼接，打警告日志，返回失败与错误摘要
        if errors:
            combined = "; ".join(errors[:4])
            logger.warning("json‑render validation failed", errors=combined)
            return False, combined

        # 全部校验通过
        return True, None