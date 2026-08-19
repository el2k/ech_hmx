from typing import Any, Dict, Optional, Tuple
from app.engine.nodes.base import BaseNodeExecutor
from app.engine.context import ExecutionContext
from app.engine.nodes.registry import register_node
from app.integrations.ai_client import AIClient
from app.core.logging import logger

@register_node("agent")
class AgentNodeExecutor(BaseNodeExecutor):
    async def execute(self, context: ExecutionContext) -> Tuple[Dict[str, Any], Optional[str]]:
        agent_id = self.config.get("agent_id")
        input_mapping = self.config.get("input_mapping", {})
        
        # Resolve inputs using mapping
        resolved_inputs = {}
        for key, template in input_mapping.items():
            resolved_inputs[key] = context.resolve_variables(template)
            
        # AI service /api/v1/agents/run expects:
        # { "agent_ids": [agent_id], "message": "...", "project_id": "..." }
        
        message = resolved_inputs.get("message") or str(resolved_inputs)
        
        payload = {
            "agent_ids": [agent_id],
            "message": message,
            "stream": False
        }
        
        # Merge other inputs into payload if needed, or session_id
        if "session_id" in resolved_inputs:
            payload["session_id"] = resolved_inputs["session_id"]
            
        active_project_id = context.project_id or "00000000-0000-0000-0000-000000000000"
        
        try:
            data = await AIClient.run_agent(active_project_id, payload)
            # SupervisorRunResponse: content
            return {"text": data.get("content", "")}, None
            
        except Exception as e:
            logger.error(f"Agent execution failed: {e}")
            raise

