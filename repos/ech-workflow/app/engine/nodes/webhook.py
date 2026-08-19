from typing import Any, Dict, Optional, Tuple
from app.engine.nodes.base import BaseNodeExecutor
from app.engine.context import ExecutionContext
from app.engine.nodes.registry import register_node

@register_node("webhook")
class WebhookNodeExecutor(BaseNodeExecutor):
    async def execute(self, context: ExecutionContext) -> Tuple[Dict[str, Any], Optional[str]]:
        # Webhook node should have body, params, and headers in context
        outputs = {
            "body": context.get_variable(f"{self.reference_key}.body"),
            "params": context.get_variable(f"{self.reference_key}.params"),
            "headers": context.get_variable(f"{self.reference_key}.headers")
        }
        return outputs, None

