# =============================================================================
# 模块：文件相关服务逻辑 (File-related service logic)
# =============================================================================
# 该模块提供了文件名处理和安全相关的工具函数，主要包括：
# 1. 文件名清理和消毒（sanitize） - 移除危险字符，确保安全存储
# 2. ASCII 文件名转换 - 生成兼容 Content-Disposition 头部的安全文件名
# 
# 设计目的：
# - 防止路径遍历攻击（如 "../" 等）
# - 防止特殊字符引起的文件系统问题
# - 确保文件名在不同操作系统和浏览器中兼容
# - 处理 Unicode 文件名在 HTTP 头部的编码问题
# =============================================================================

import re
import unicodedata
from pathlib import Path
from urllib.parse import quote


# =============================================================================
# 函数1: 文件名消毒（安全存储）
# =============================================================================

def sanitize_filename(name: str, limit: int = 100) -> str:
    """
    对文件名进行消毒处理，确保安全存储。

    执行流程：
    1. 替换路径分隔符（防止路径遍历）
    2. 用正则表达式移除所有非安全字符
    3. 限制文件名长度（保留扩展名）

    安全字符范围：A-Z, a-z, 0-9, ., _, -
    所有其他字符将被替换为下划线 "_"

    使用场景：
    - 用户上传文件时，对原始文件名进行消毒
    - 存储到文件系统前确保文件名安全

    Args:
        name: 原始文件名
        limit: 最大长度限制（默认100字符）

    Returns:
        str: 消毒后的安全文件名

    Examples:
        >>> sanitize_filename("../../../etc/passwd")
        "____etc_passwd"
        >>> sanitize_filename("hello@world!.txt")
        "hello_world_.txt"
        >>> sanitize_filename("very_long_name" * 10 + ".pdf", limit=20)
        "very_long_name.pdf"  # 保留扩展名
    """
    # =====================================================================
    # 步骤1: 替换路径分隔符
    # =====================================================================
    # 防止路径遍历攻击：将 "\" 和 "/" 替换为 "_"
    # 处理 ".." 序列防止目录遍历
    name = name.replace("\\", "_").replace("/", "_").replace("..", ".")

    # =====================================================================
    # 步骤2: 移除不安全字符
    # =====================================================================
    # 只保留字母、数字、点、下划线、连字符
    # 其他字符全部替换为下划线
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)

    # =====================================================================
    # 步骤3: 限制文件名长度
    # =====================================================================
    if len(name) <= limit:
        return name

    # 如果文件名包含扩展名，在截断时保留扩展名
    if "." in name:
        # 分离基名和扩展名
        base, ext = name.rsplit(".", 1)
        # 保留扩展名，截断基名
        # max(1, ...) 确保至少保留1个字符
        base = base[: max(1, limit - len(ext) - 1)]
        return f"{base}.{ext}"

    # 没有扩展名，直接截断
    return name[:limit]


# =============================================================================
# 函数2: 获取安全的 ASCII 文件名
# =============================================================================

def get_safe_ascii_filename(original_name: str, fallback_id: str = "file") -> str:
    """
    获取安全的 ASCII 文件名，用于 Content-Disposition HTTP 头部。

    背景说明：
    - Content-Disposition 头部中的文件名建议使用 ASCII 字符
    - 非 ASCII 字符（如中文）可能导致浏览器显示乱码或解析错误
    - 该函数将 Unicode 文件名转换为 ASCII 安全的版本

    执行流程：
    1. 清理原始文件名（移除回车换行）
    2. 使用 Unicode NFKD 规范化（分解组合字符）
    3. 移除非 ASCII 字符
    4. 移除可能破坏 HTTP 头部的特殊字符（"", \, ;, ,）
    5. 确保文件名保留扩展名

    使用场景：
    - 文件下载时的 Content-Disposition: attachment; filename="..."
    - 需要确保文件名在不同浏览器中正确显示

    Args:
        original_name: 原始文件名（可能包含 Unicode）
        fallback_id: 当名称为空时的备用标识符（默认 "file"）

    Returns:
        str: 安全的 ASCII 文件名

    Examples:
        >>> get_safe_ascii_filename("中文文件名.pdf")
        ".pdf"  # 中文被移除，仅保留扩展名
        >>> get_safe_ascii_filename("hello.txt")
        "hello.txt"
        >>> get_safe_ascii_filename("")
        "file"
        >>> get_safe_ascii_filename('test"with;quotes,comma.txt')
        "testwithquotescomma.txt"
    """
    # =====================================================================
    # 步骤1: 清理原始文件名
    # =====================================================================
    # 移除回车换行，去除首尾空白
    safe_name = original_name or "file"
    safe_name = safe_name.replace("\r", " ").replace("\n", " ").strip()

    # =====================================================================
    # 步骤2: Unicode 规范化
    # =====================================================================
    # NFKD (Normalization Form KD) 将字符分解为组合形式
    # 例如: "é" -> "e" + "´" (组合字符)
    # 这样后续的 ASCII 过滤可以保留基础字符
    normalized_name = unicodedata.normalize("NFKD", safe_name)

    # 尝试将规范化后的字符串编码为 ASCII，忽略非 ASCII 字符
    # 例如: "é" -> 忽略重音符号，保留 "e"
    ascii_name_bytes = normalized_name.encode("ascii", "ignore")
    ascii_name = ascii_name_bytes.decode("ascii") if ascii_name_bytes else ""

    # =====================================================================
    # 步骤3: 移除 HTTP 头部不安全字符
    # =====================================================================
    # RFC 5987 / RFC 6266 规定，文件名中应避免以下字符：
    # - 双引号 (") - 破坏引用
    # - 反斜杠 (\) - 转义字符
    # - 分号 (;) - 参数分隔符
    # - 逗号 (,) - 参数分隔符
    ascii_name = "".join(
        ch if ch.isascii() and ch not in {'"', "\\", ";", ","} else "_"
        for ch in ascii_name
    ).strip()

    # =====================================================================
    # 步骤4: 处理扩展名
    # =====================================================================
    # 从原始文件名中提取扩展名
    suffix = Path(safe_name).suffix

    # 如果所有字符都被过滤掉了，使用备用 ID + 扩展名
    if not ascii_name:
        return f"{fallback_id}{suffix}"

    # 确保 ASCII 文件名保留正确的扩展名
    # 注意：这里检查是否已包含扩展名（不区分大小写）
    if suffix and not ascii_name.lower().endswith(suffix.lower()):
        return f"{ascii_name}{suffix}"

    return ascii_name