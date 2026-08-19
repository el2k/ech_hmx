"""
LLM service for text processing tasks like QA pair generation.
"""

from typing import List, Optional, Dict, Any
import json
import logging
from openai import OpenAI

from ..config import get_settings

logger = logging.getLogger(__name__)
# 大模型服务类，提供与大语言模型（LLM）交互的功能，主要用于文本处理任务，如问答对生成。
class LLMService:
    """Service for interacting with LLMs for text processing."""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        self.base_url = base_url or settings.openai_compatible_base_url
        
        # Determine model to use
        self.model = model
        
        if not self.model:
            logger.error("No LLM model specified and no default available.")
            raise ValueError("LLM model name is required")
        
        # Check if the candidate model is likely an embedding model (which can't chat)
        if any(x in self.model.lower() for x in ["embedding", "ada", "bge"]):
            logger.warning(f"Model '{self.model}' appears to be an embedding model. Chat model required for LLM tasks.")
            # We don't have a fallback anymore, so this might fail at the API level if not corrected by caller
            pass

        if not self.api_key:
            logger.warning("No LLM API key provided. LLM-based features will be unavailable.")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        ) if self.api_key else None

    def _parse_json(self, content: str) -> Dict[str, Any]:
        """Robustly parse JSON from LLM response content."""
        if not content:
            return {}
            
        clean_content = content.strip()
        
        # 1. Try direct loading
        # 尝试直接解析 JSON
        try:
            return json.loads(clean_content)
        except json.JSONDecodeError:
            pass
            
        # 2. Try extracting from markdown blocks
        # 尝试从 Markdown 块中提取 JSON 
        import re
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_content)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass
                
        # 3. Try finding the first '{' and last '}'
        # 尝试找到第一个 '{' 和最后一个 '}' 之间的内容
        start_idx = clean_content.find("{")
        end_idx = clean_content.rfind("}")
        if start_idx != -1 and end_idx != -1:
            try:
                return json.loads(clean_content[start_idx:end_idx+1])
            except json.JSONDecodeError:
                pass
                
        return {}

    async def generate_qa_pairs(self, text: str) -> List[Dict[str, str]]:
        """
        Generate Q&A pairs from a text chunk.
        """
        if not self.client:
            logger.error("LLM client not initialized. Cannot generate QA pairs.")
            return []

        if not text.strip():
            return []

        prompt = f"""
你是一个专业的知识库问答对生成专家。请根据以下文本生成高质量的问答对。

## 生成规则
1. **问题多样性**：使用不同问法（什么是/如何/为什么/哪些/何时/在哪里）
2. **问题具体性**：问题必须具体明确，直接指向知识点
3. **答案完整性**：答案必须完整准确，可直接回答问题
4. **独立可理解**：问题和答案脱离原文依然可理解，避免使用代词
5. **关键词覆盖**：确保文本中的关键实体、概念、数字、专有名词都被覆盖
6. **数量要求**：尽可能多地提取，只要是独立知识点都应生成问答对

## 输出格式
返回JSON对象: {{"qa_pairs": [{{"question": "...", "answer": "..."}}]}}

## 待处理文本
---
{text}
---
"""

        try:
            import asyncio
            loop = asyncio.get_event_loop()
            
            # Simple heuristic for JSON support
            is_json_supported = any(m in (self.model or "") for m in ["gpt-4", "gpt-3.5-turbo", "gpt-4o"])
            
            response = await loop.run_in_executor(
                None,
                # 核心调用 LLM API 生成问答对
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是一个资深的文档分析专家，擅长从文本中提取详尽的知识点。你必须始终返回有效的 JSON 对象，包含 'qa_pairs' 字段。"},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"} if is_json_supported else None,
                    temperature=0.3,
                )
            )
            # 得到 LLM 响应内容
            content = response.choices[0].message.content
            logger.info(f"LLM QA Response (Length: {len(content)}):\n{content[:500]}...")  # Log first 500 chars

            data = self._parse_json(content)
            
            if not data:
                logger.error(f"Failed to parse LLM response as JSON: {content}")
                return []
                
            # Normalize results
            if isinstance(data, list):
                results = data
            elif isinstance(data, dict):
                if "qa_pairs" in data and isinstance(data["qa_pairs"], list):
                    results = data["qa_pairs"]
                else:
                    # Look for any list in the dict that contains dictionaries with "question"
                    results = []
                    for val in data.values():
                        if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict) and "question" in val[0]:
                            results = val
                            break
                    if not results and "question" in data and "answer" in data:
                        results = [data]
            else:
                results = []
            
            valid_results = [item for item in results if isinstance(item, dict) and "question" in item and "answer" in item]
            logger.info(f"Parsed {len(valid_results)} QA pairs from chunk (Input len: {len(text)})")
            
            # Final validation
            return valid_results

        except Exception as e:
            logger.error(f"Error generating QA pairs with LLM: {str(e)}")
            return []

_llm_service: Optional[LLMService] = None

def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        # This will now fail if no model is provided, which is intended.
        # Fallback to a value that will clearly fail if used without project context.
        raise RuntimeError("Global LLM service must be initialized with a project-specific model.")
    return _llm_service

async def get_llm_service_for_project(project_id) -> LLMService:
    """Resolve and construct an LLMService scoped to the given project.
    
    Uses the same configuration model as embedding.
    """
    from sqlalchemy import select, text
    from ..database import get_db_session
    from ..models.embedding_config import EmbeddingConfig

    if project_id is None:
        return get_llm_service()

    # Query active config
    async with get_db_session() as db:
        result = await db.execute(
            select(EmbeddingConfig).where(
                EmbeddingConfig.project_id == project_id,
                EmbeddingConfig.is_active.is_(True),
            )
        )
        rec = result.scalar_one_or_none()

    if rec is None:
        logger.error(f"No active embedding/LLM configuration found for project {project_id}")
        raise ValueError(f"No LLM configuration found for project {project_id}. Please configure an AI provider for this project.")

    # Use the same API key and Base URL as the embedding config
    # Note: We might want a separate LLM config table later, 
    # but for now RAG providers usually use the same credentials for both.
    
    # CRITICAL: If the model is an embedding model, we MUST fallback to a chat model
    # for QA generation, otherwise the API will return an error.
    # CRITICAL: If the model is an embedding model, we MUST fallback to a chat model
    # for QA generation, otherwise the API will return an error.
    model = rec.model
    # 如果 "embedding" 在模型名称中，则尝试从项目配置中获取默认的聊天模型
    if "embedding" in model.lower():
        # Try to find the default chat model from api_project_ai_configs
        try:
            # Re-acquire DB session for raw query
            async with get_db_session() as db:
                result = await db.execute(
                    text("SELECT default_chat_model FROM api_project_ai_configs WHERE project_id = :pid AND deleted_at IS NULL"),
                    {"pid": project_id}
                )
                chat_config = result.scalar_one_or_none()
            if chat_config:
                logger.info(f"Model '{model}' is an embedding model. Falling back to project default chat model '{chat_config}'.")
                model = chat_config
            else:
                logger.error(f"Model '{model}' is an embedding model and no default chat model found in DB for project {project_id}.")
                # Since we have no global fallback, we'll keep the model name but it will likely fail on API call
                pass
        except Exception as e:
            logger.error(f"Failed to query api_project_ai_configs for project {project_id}: {e}")
            pass

    return LLMService(
        api_key=rec.api_key,
        base_url=rec.base_url,
        model=model
    )
