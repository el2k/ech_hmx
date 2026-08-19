from typing import Any, Dict, Optional, Tuple
from app.engine.nodes.base import BaseNodeExecutor
from app.engine.context import ExecutionContext
from app.engine.nodes.registry import register_node
from datetime import datetime

@register_node("timer")
class TimerNodeExecutor(BaseNodeExecutor):
    async def execute(self, context: ExecutionContext) -> Tuple[Dict[str, Any], Optional[str]]:
        # Timer node can inject metadata like execution timestamp
        outputs = {
            "timestamp": datetime.utcnow().isoformat()
        }
        return outputs, None

