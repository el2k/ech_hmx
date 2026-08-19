import httpx
from typing import Optional, List, Dict, Any
from app.config import settings
from app.core.logging import logger
from app.integrations.http_client import HttpClient

class AIClient:
    @staticmethod
    async def chat_completions(
        project_id: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call AI service chat completions endpoint.
        """
        try:
            client = await HttpClient.get_client()
            url = f"{settings.AI_SERVICE_URL}/api/v1/chat/completions"
            params = {"project_id": project_id}
            
            # Internal call, no Authorization header needed
            response = await client.post(
                url,
                json=payload,
                params=params,
                timeout=60.0
            )
            
            if response.status_code != 200:
                logger.error(f"AI Service chat completions error: {response.status_code} - {response.text}")
                raise Exception(f"AI Service chat completions failed with status {response.status_code}")
                
            return response.json()
        except Exception as e:
            logger.error(f"AI Service chat completions failed: {e}")
            raise

    @staticmethod
    async def run_agent(
        project_id: str,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call AI service agents run endpoint.
        """
        try:
            client = await HttpClient.get_client()
            url = f"{settings.AI_SERVICE_URL}/api/v1/agents/run"
            params = {"project_id": project_id}
            
            # Internal call, no Authorization header needed
            response = await client.post(
                url,
                json=payload,
                params=params,
                timeout=120.0 # Agent runs can take longer
            )
            
            if response.status_code != 200:
                logger.error(f"AI Service Agent Run error: {response.status_code} - {response.text}")
                raise Exception(f"AI Service Agent Run failed with status {response.status_code}")
                
            return response.json()
        except Exception as e:
            logger.error(f"AI Service agent run failed: {e}")
            raise

    @staticmethod
    async def cancel_agent_run(
        project_id: str,
        run_id: str,
        payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Call AI service agents cancel endpoint.
        """
        try:
            client = await HttpClient.get_client()
            url = f"{settings.AI_SERVICE_URL}/api/v1/agents/run/{run_id}/cancel"
            params = {"project_id": project_id}
            
            # Internal call, no Authorization header needed
            response = await client.post(
                url,
                json=payload or {},
                params=params
            )
            
            if response.status_code != 202:
                logger.error(f"AI Service Agent Cancel error: {response.status_code} - {response.text}")
                raise Exception(f"AI Service Agent Cancel failed with status {response.status_code}")
                
            return response.json()
        except Exception as e:
            logger.error(f"AI Service agent cancel failed: {e}")
            raise

    @staticmethod
    async def get_tool(
        project_id: str,
        tool_id: str
    ) -> Dict[str, Any]:
        """
        Get tool details from AI service.
        """
        try:
            client = await HttpClient.get_client()
            url = f"{settings.AI_SERVICE_URL}/api/v1/tools/{tool_id}"
            params = {"project_id": project_id}
            
            response = await client.get(
                url,
                params=params
            )
            
            if response.status_code != 200:
                logger.error(f"AI Service Get Tool error: {response.status_code} - {response.text}")
                raise Exception(f"AI Service Get Tool failed with status {response.status_code}")
                
            return response.json()
        except Exception as e:
            logger.error(f"AI Service get tool failed: {e}")
            raise

    @staticmethod
    async def execute_tool(
        project_id: str,
        tool_id: str,
        inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute tool via AI service.
        """
        try:
            client = await HttpClient.get_client()
            url = f"{settings.AI_SERVICE_URL}/api/v1/tools/{tool_id}/execute"
            params = {"project_id": project_id}
            payload = {"inputs": inputs}
            
            response = await client.post(
                url,
                json=payload,
                params=params,
                timeout=60.0
            )
            
            if response.status_code != 200:
                logger.error(f"AI Service Execute Tool error: {response.status_code} - {response.text}")
                raise Exception(f"AI Service Execute Tool failed with status {response.status_code}")
                
            return response.json()
        except Exception as e:
            logger.error(f"AI Service execute tool failed: {e}")
            raise

