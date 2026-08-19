"""MCP访问Token工具函数."""

from __future__ import annotations

from typing import Any, Dict, Optional

import aiohttp


async def get_mcp_access_token(
    supabase_token: str,
    base_mcp_url: str,
) -> Optional[Dict[str, Any]]:
    """通过Supabase令牌交换MCP访问Token."""

    form_data = {
        "client_id": "mcp_default",
        "subject_token": supabase_token,
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "resource": base_mcp_url.rstrip("/") + "/mcp",
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
    }
    # 这里使用aiohttp库发起HTTP POST请求，向MCP的OAuth2 Token Endpoint发送表单数据，以交换Supabase令牌为MCP访问Token。
    async with aiohttp.ClientSession() as session:
        async with session.post(
            base_mcp_url.rstrip("/") + "/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=form_data,
        ) as response:
            if response.status == 200:
                return await response.json()
            detail = await response.text()
            raise RuntimeError(f"Failed to exchange MCP token: {detail}")
