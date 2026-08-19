"""
编码实用工具，用于标识符的处理。
提供了一个 Base62 编码器，用于 channel_id 的生成。
我们避免使用外部依赖；Base62 的实现是通过将输入字节视为大整数并转换为 Base62 字母表来实现的。
这保持了对相同输入字符串的确定性、可逆映射。
"""

from __future__ import annotations

from typing import Final

_BASE62_ALPHABET: Final[str] = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_BASE62_BASE: Final[int] = 62


def _int_to_base62(n: int) -> str:
    """Convert a non-negative integer to a base62 string.

    Args:
        n: Non-negative integer
    Returns:
        Base62 representation using [0-9A-Za-z].
    """
    if n == 0:
        return "0"
    digits = []
    base = _BASE62_BASE
    while n > 0:
        n, rem = divmod(n, base)
        digits.append(_BASE62_ALPHABET[rem])
    return "".join(reversed(digits))


def encode_channel_id(raw_string: str) -> str:
    """
    编码 channel_id 为 Base62 字符串。
    Implementation details:
    - 输出字符串是通过将输入字符串编码为 UTF-8 字节，然后将字节解释为大整数，并转换为 Base62 字符串来实现的。
    - 这保持了对相同输入字符串的确定性映射，并且是
    可逆的（如果需要，可以通过解析回整数再转回字节来实现）。
    """

    if raw_string is None:
        return "0"
    data = raw_string.encode("utf-8")
    # Interpret bytes as big integer (unsigned)
    int_value = int.from_bytes(data, byteorder="big", signed=False) if data else 0
    return _int_to_base62(int_value)




def _base62_to_int(s: str) -> int:
    """Convert a base62 string to integer.

    Raises ValueError on invalid characters.
    """
    if not s:
        return 0
    n = 0
    base = _BASE62_BASE
    alphabet = _BASE62_ALPHABET
    for ch in s.strip():
        idx = alphabet.find(ch)
        if idx == -1:
            raise ValueError(f"Invalid base62 character: {ch}")
        n = n * base + idx
    return n

# 解码
def decode_channel_id(encoded: str) -> str:
    """Decode a Base62-encoded channel identifier back to its original string.

    This reverses encode_channel_id().
    """
    try:
        int_value = _base62_to_int(encoded)
    except Exception as exc:
        raise ValueError(f"Invalid base62 string: {encoded}") from exc

    if int_value == 0:
        return ""
    # minimal bytes needed for big-endian representation
    byte_len = (int_value.bit_length() + 7) // 8
    data = int_value.to_bytes(byte_len, byteorder="big", signed=False)
    return data.decode("utf-8")
