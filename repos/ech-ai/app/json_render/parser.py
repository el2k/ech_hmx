"""Parse mixed LLM output (text + ```spec JSONL blocks) into json‑render patches.
解析大模型混合输出：普通自然文本 + ```spec 围栏包裹的JSONL补丁块，输出json‑render补丁集合
该补丁遵循 RFC6902 JSON‑Patch 风格，op/path 为核心字段，用于动态渲染UI组件
"""

from __future__ import annotations  # 延迟注解求值，支持dataclass内部自引用类型提示，Python3.7+兼容

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 导入常量：json‑render围栏标记，一般为 ```spec  和 ```
from app.json_render.schema_manager import (
    JSON_RENDER_SPEC_FENCE_CLOSE,
    JSON_RENDER_SPEC_FENCE_OPEN,
)
from app.json_render.validator import JsonRenderPatchValidator  # 补丁业务校验器


@dataclass
class JsonRenderParseResult:
    """LLM输出解析结果数据载体
    存储解析后的纯文本、提取出来的json‑render补丁列表、校验状态、错误信息
    """
    text_content: str = ""  # 围栏之外，普通大模型自然语言文本
    patches: List[Dict[str, Any]] = field(default_factory=list)  # 解析成功的JSON‑Patch补丁数组
    has_json_render: bool = False  # 是否成功提取到json‑render补丁块
    is_valid: bool = True  # 补丁整体是否通过业务校验
    validation_error: Optional[str] = None  # 校验失败时存放错误描述，成功为None


class JsonRenderParser:
    """从模型输出中提取并校验 json‑render patch 补丁行
    输入混合文本：自然语言 + ```spec ... ```围栏内每行一条JSON对象(JSONL格式)
    输出结构化解析结果 JsonRenderParseResult
    """

    def __init__(self, validator: Optional[JsonRenderPatchValidator] = None) -> None:
        """构造解析器，可注入自定义校验器；不传则实例化默认校验器"""
        self._validator = validator or JsonRenderPatchValidator()

    def parse(self, content: str) -> JsonRenderParseResult:
        """主解析入口：解析混合文本 + 围栏包裹的spec流式输出
        算法逻辑：逐行遍历，状态机标记是否处于spec围栏内部；围栏内尝试解析JSONL补丁，围栏外收集普通文本
        :param content: LLM原始完整输出字符串
        :return: JsonRenderParseResult 解析结果对象
        """
        in_spec_fence = False  # 状态标记：当前是否处在 ```spec 围栏内部
        text_lines: List[str] = []  # 存放围栏外普通文本行
        patches: List[Dict[str, Any]] = []  # 存放解析成功的patch补丁字典

        # 将原始输出按换行切分成一行一行处理，兼容流式输出逐行
        for raw_line in content.splitlines():
            line = raw_line.rstrip("\r")  # 去掉Windows回车符\r，保留\n换行
            trimmed = line.strip()  # 去除首尾空白，用于判断围栏标记

            # -------- 围栏开始标记：进入spec块 --------
            if not in_spec_fence and trimmed.startswith(JSON_RENDER_SPEC_FENCE_OPEN):
                in_spec_fence = True
                continue  # 围栏标记行本身丢弃，不加入文本/补丁

            # -------- 围栏结束标记：退出spec块 --------
            if in_spec_fence and trimmed == JSON_RENDER_SPEC_FENCE_CLOSE:
                in_spec_fence = False
                continue  # 结束围栏标记行丢弃

            # 尝试把当前行解析为patch补丁对象（仅围栏内部行会解析出有效patch）
            parsed_patch = self._parse_patch_line(trimmed)
            if parsed_patch is not None:
                patches.append(parsed_patch)
                continue  # 解析成功，则该行属于补丁，不再加入普通文本

            # 不在围栏内：该行属于普通自然语言文本，保留原始行（不去除首尾空格）
            if not in_spec_fence:
                text_lines.append(line)

        # 拼接所有普通文本行，首尾去空格
        text_content = "\n".join(text_lines).strip()

        # 没有提取到任何patch，直接返回，has_json_render=False
        if not patches:
            return JsonRenderParseResult(text_content=text_content)

        # 存在补丁，调用校验器做业务合法性校验
        is_valid, error = self._validator.validate(patches)
        return JsonRenderParseResult(
            text_content=text_content,
            patches=patches,
            has_json_render=True,
            is_valid=is_valid,
            validation_error=error,
        )

    @staticmethod
    def _parse_patch_line(line: str) -> Optional[Dict[str, Any]]:
        """【静态工具方法】单行JSON解析，校验JSON‑Patch最小格式约束
        只处理以 { 开头的行；JSON解析失败、不是字典、缺少op/path、path不以/开头直接返回None
        RFC6902 JSON‑Patch 最小要求：op(操作类型)、path(目标路径，以/开头)
        :param line: 去除首尾空白后的一行字符串
        :return: 合法patch字典；格式非法返回None
        """
        # 空字符串，或者不是以{开头，直接跳过
        if not line or not line.startswith("{"):
            return None
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            # JSON语法错误，直接丢弃该行，不抛异常
            return None
        # 必须是字典对象，数组/数字/字符串全部丢弃
        if not isinstance(parsed, dict):
            return None

        op = parsed.get("op")
        path = parsed.get("path")
        # op必须字符串，path必须字符串，并且path必须以斜杠开头(RFC6902标准)
        if not isinstance(op, str) or not isinstance(path, str) or not path.startswith("/"):
            return None

        # 全部基础校验通过，返回解析完成的patch字典
        return parsed