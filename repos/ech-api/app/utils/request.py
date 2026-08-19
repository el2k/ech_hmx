# -*- coding: utf-8 -*-
"""HTTP request utilities."""
# 模块说明：HTTP 请求工具函数，提供从请求中提取客户端信息（IP地址、语言偏好等）的能力。

import ipaddress
from typing import Optional
from fastapi import Request


def get_client_language(request: Request, provided_language: Optional[str] = None) -> Optional[str]:
    """
    从请求中获取客户端的首选语言。

    优先级（从高到低）：
        1. 如果提供了 provided_language 且不为空，直接使用
        2. Accept-Language 请求头中的第一个语言（权重最高）

    Args:
        request: FastAPI Request 对象
        provided_language: 请求体中提供的可选语言代码

    Returns:
        str | None: 客户端的首选语言代码（如 'en'、'zh-CN'），获取失败返回 None
    """
    # 1. 优先使用请求体传入的语言
    if provided_language and provided_language.strip():
        return provided_language.strip()
    
    # 2. 从 Accept-Language 请求头获取
    accept_language = request.headers.get("Accept-Language")
    if accept_language:
        # 解析 Accept-Language 头
        # 格式示例："en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"
        # 取第一个语言（权重最高）
        languages = accept_language.split(",")
        if languages:
            # 取第一个语言，去掉质量值（如 ;q=0.9）
            first_lang = languages[0].split(";")[0].strip()
            if first_lang:
                return first_lang
    
    return None


# ------------------- IP 地址解析辅助函数 -------------------

def _normalize_ip_candidate(value: str) -> str:
    """
    规范化 IP 地址候选字符串。

    处理常见的格式：
        - 纯 IP: "1.2.3.4"
        - IP + 端口: "1.2.3.4:12345"
        - IPv6 加端口: "[2001:db8::1]:12345"
        - 纯 IPv6: "2001:db8::1"

    此函数用于从各种请求头中提取纯净的 IP 地址。

    Args:
        value: 待规范化的 IP 字符串

    Returns:
        str: 规范后的 IP 地址，无效输入返回空字符串
    """
    v = (value or "").strip().strip('"').strip("'")  # 去除首尾空白和引号
    if not v:
        return ""

    # 处理 IPv6 带端口的情况：[addr]:port
    if v.startswith("[") and "]" in v:
        inside = v[1 : v.index("]")]  # 取方括号内的部分
        return inside.strip()

    # 处理 IPv4 + 端口：看起来像 "x.x.x.x:port"，且只有一个冒号且包含点号
    # （IPv6 有多个冒号，所以不盲目分割）
    if v.count(":") == 1 and "." in v:
        host, _port = v.split(":", 1)  # 按第一个冒号分割，取主机部分
        return host.strip()

    return v


def _is_valid_ip(value: str) -> bool:
    """
    验证字符串是否为有效的 IP 地址（IPv4 或 IPv6）。

    Args:
        value: 待验证的 IP 字符串

    Returns:
        bool: 有效返回 True，否则返回 False
    """
    try:
        ipaddress.ip_address(value)
        return True
    except Exception:
        return False


def _is_public_ip(value: str) -> bool:
    """
    判断 IP 地址是否为公网可路由地址（全局可路由）。

    使用 Python 3 的 ipaddress 模块的 is_global 属性。
    私有IP（10.0.0.0/8、192.168.0.0/16、127.0.0.1等）返回 False。

    Args:
        value: IP 地址字符串

    Returns:
        bool: 公网 IP 返回 True，私有/保留地址返回 False
    """
    try:
        ip = ipaddress.ip_address(value)
        return ip.is_global
    except Exception:
        return False


def _pick_best_ip_from_xff(x_forwarded_for: str) -> Optional[str]:
    """
    从 X-Forwarded-For 链中选择最佳的客户端 IP。

    选择策略：
        1. 优先选择列表中的第一个有效公网 IP
        2. 如果没有公网 IP，则返回第一个有效 IP

    X-Forwarded-For 格式：client, proxy1, proxy2, ...
    最左侧的 IP 是最初发起请求的客户端。

    Args:
        x_forwarded_for: X-Forwarded-For 头原始值

    Returns:
        str | None: 选中的客户端 IP，没有则返回 None
    """
    if not x_forwarded_for:
        return None

    # 按逗号分割，去除首尾空白
    parts = [p.strip() for p in x_forwarded_for.split(",") if p.strip()]
    
    # 规范化每个候选 IP，过滤无效地址
    normalized = []
    for p in parts:
        candidate = _normalize_ip_candidate(p)
        if candidate and _is_valid_ip(candidate):
            normalized.append(candidate)

    # 优先选择公网 IP
    for ip in normalized:
        if _is_public_ip(ip):
            return ip

    # 没有公网 IP，返回第一个有效 IP
    return normalized[0] if normalized else None


# ------------------- 主要导出函数 -------------------

def get_client_ip(request: Request, provided_ip: Optional[str] = None) -> Optional[str]:
    """
    从请求中获取真实的客户端 IP 地址。

    优先级（从高到低）：
        1. 如果提供了 provided_ip 且不为空，直接使用
        2. X-Forwarded-For 头（由 nginx 等代理设置，取第一个 IP）
        3. X-Real-IP 头（nginx 的 real_ip_header 指令设置）
        4. CF-Connecting-IP 头（Cloudflare 设置）
        5. True-Client-IP 头（某些 CDN 设置）
        6. request.client.host（直连 IP，可能为代理 IP）

    为何需要这么多种头？
        - 不同代理/CDN 服务设置不同的头部
        - X-Forwarded-For 可能被伪造，需要谨慎处理
        - 在某些部署架构中，特定头部更可靠

    Args:
        request: FastAPI Request 对象
        provided_ip: 请求体中提供的可选 IP 地址

    Returns:
        str | None: 客户端的真实 IP 地址，无法获取返回 None
    """
    # 1. 优先使用请求体传入的 IP
    if provided_ip and provided_ip.strip():
        ip_value = _normalize_ip_candidate(provided_ip)
        return ip_value if ip_value else provided_ip.strip()
    
    # 2. X-Forwarded-For: 格式为 "client, proxy1, proxy2, ..."
    #    client 是最初的客户端 IP
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        best = _pick_best_ip_from_xff(x_forwarded_for)
        if best:
            return best
    
    # 3. X-Real-IP: nginx 通过 real_ip_header 指令设置
    #    通常包含代理转发的真实客户端 IP
    x_real_ip = request.headers.get("X-Real-IP")
    if x_real_ip:
        ip_value = _normalize_ip_candidate(x_real_ip)
        return ip_value if ip_value else x_real_ip.strip()
    
    # 4. CF-Connecting-IP: Cloudflare 专用头
    #    Cloudflare 会覆盖 X-Forwarded-For，使用此头更可靠
    cf_connecting_ip = request.headers.get("CF-Connecting-IP")
    if cf_connecting_ip:
        ip_value = _normalize_ip_candidate(cf_connecting_ip)
        return ip_value if ip_value else cf_connecting_ip.strip()
    
    # 5. True-Client-IP: 某些 CDN 服务商使用
    true_client_ip = request.headers.get("True-Client-IP")
    if true_client_ip:
        ip_value = _normalize_ip_candidate(true_client_ip)
        return ip_value if ip_value else true_client_ip.strip()
    
    # 6. 最终回退：FastAPI 获取的直连 IP
    #    在没有代理的情况下，这就是真实客户端 IP
    #    有代理时，这是最后一个代理的 IP
    if request.client and request.client.host:
        ip_value = _normalize_ip_candidate(request.client.host)
        return ip_value if ip_value else request.client.host
    
    return None