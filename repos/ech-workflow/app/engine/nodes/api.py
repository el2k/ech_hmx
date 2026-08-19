import httpx
import json
from typing import Any, Dict, Optional, Tuple
from app.engine.nodes.base import BaseNodeExecutor
from app.engine.context import ExecutionContext
from app.core.logging import logger
from app.integrations.http_client import get_http_client
from app.engine.nodes.registry import register_node

@register_node("api")
class APINodeExecutor(BaseNodeExecutor):
    async def execute(self, context: ExecutionContext) -> Tuple[Dict[str, Any], Optional[str]]:
        method = self.config.get("method", "GET").upper()
        url = context.resolve_template(self.config.get("url", ""))
        
        headers = {h["key"]: context.resolve_template(h["value"]) for h in self.config.get("headers", [])}
        params = {p["key"]: context.resolve_template(p["value"]) for p in self.config.get("params", [])}
        
        body_type = self.config.get("body_type", "none")
        data = None
        json_data = None
        
        if body_type == "json":
            json_body = context.resolve_template(self.config.get("body", "{}"))
            try:
                json_data = json.loads(json_body)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON body: {e}")
                json_data = {}
        elif body_type == "x-www-form-urlencoded":
            data = {item["key"]: context.resolve_template(item["value"]) for item in self.config.get("form_url_encoded", [])}
        elif body_type == "raw":
            data = context.resolve_template(self.config.get("body", ""))

        client = await get_http_client()
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
            data=data
        )
        
        try:
            body = response.json()
        except json.JSONDecodeError:
            body = response.text
            
        outputs = {
            "body": body,
            "status_code": response.status_code,
            "headers": dict(response.headers)
        }
        
        return outputs, None

