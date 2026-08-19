"""Chat completion service for OpenAI‑compatible API.
面向 OpenAI 兼容接口的聊天补全核心服务。

本服务根据 LLMProvider 表中的 provider_kind，将聊天请求代理转发到不同的大模型服务商。
支持 OpenAI/兼容接口、Anthropic、Google Gemini 三类后端；同时内置 Agent 自动工具调用循环，
可在服务端自动执行工具并将结果回填给大模型，直到生成最终回答。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

import google.generativeai as genai
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.exceptions import TGOAIServiceException
from app.models.llm_provider import LLMProvider
from app.models.tool import Tool
from app.schemas.chat import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ChoiceMessage,
    DeltaMessage,
    FunctionCall,
    FunctionDefinition,
    StreamChoice,
    ToolCall,
    ToolDefinition,
    Usage,
    create_completion_id,
)
from app.services.llm_provider_service import LLMProviderService
from app.services.rag_service import rag_service_client
from app.services.tool_executor import ToolExecutor

logger = get_logger(__name__)


# =============================================================================
# 自定义业务异常
# =============================================================================


class ProviderNotFoundError(TGOAIServiceException):
    """指定的LLM服务商在数据库中不存在时抛出"""

    def __init__(self, provider_id: uuid.UUID):
        super().__init__(
            code="PROVIDER_NOT_FOUND",
            message=f"LLM provider with ID {provider_id} not found",
            details={"provider_id": str(provider_id)},
        )


class ProviderNotActiveError(TGOAIServiceException):
    """指定的LLM服务商已被停用（is_active=False）时抛出"""

    def __init__(self, provider_id: uuid.UUID):
        super().__init__(
            code="PROVIDER_NOT_ACTIVE",
            message=f"LLM provider with ID {provider_id} is not active",
            details={"provider_id": str(provider_id)},
        )


class UnsupportedProviderError(TGOAIServiceException):
    """服务商类型不在支持范围内时抛出"""

    def __init__(self, provider_kind: str):
        super().__init__(
            code="UNSUPPORTED_PROVIDER",
            message=f"Provider kind '{provider_kind}' is not supported",
            details={"provider_kind": provider_kind},
        )


class ChatCompletionError(TGOAIServiceException):
    """调用大模型聊天接口过程中发生错误时抛出"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            code="CHAT_COMPLETION_ERROR",
            message=message,
            details=details or {},
        )


# =============================================================================
# Chat Service 主服务类
# =============================================================================


class ChatService:
    """Service for handling chat completions via various LLM providers.
    多模型统一聊天补全服务，对外输出 OpenAI 兼容的请求/响应格式。
    支持非流式、SSE 流式两种模式；支持自动工具调用 Agent 循环。
    """

    # 服务商类型常量
    OPENAI_PROVIDERS = {"openai", "openai_compatible"}
    ANTHROPIC_PROVIDER = "anthropic"
    GOOGLE_PROVIDER = "google"

    def __init__(self, db: AsyncSession) -> None:
        """
        :param db: SQLAlchemy 异步数据库会话
        """
        self.db = db
        self.provider_service = LLMProviderService(db)
        self._logger = logger

    # -------------------------------------------------------------------------
    # 对外公开 API
    # -------------------------------------------------------------------------

    async def create_completion(
        self,
        request: ChatCompletionRequest,
        project_id: uuid.UUID,
    ) -> ChatCompletionResponse:
        """创建非流式聊天补全，可选开启自动工具调用 Agent 循环。

        两种模式：
        1. auto_execute_tools=False：标准 OpenAI 透传模式，只调用一次 LLM 直接返回
        2. auto_execute_tools=True：服务端 Agent 循环，自动执行工具并回填结果，最多 max_tool_rounds 轮
        """
        # 校验并获取服务商配置
        provider = await self._get_provider(request.provider_id, project_id)
        provider_kind = (provider.provider_kind or "").lower()

        # 合并三类工具来源：请求自带tools + 数据库tool_ids + RAG集合collection_ids
        merged_tools = await self._merge_tools(request, project_id)
        request.tools = merged_tools

        # 最大工具调用轮次，默认5轮防止死循环
        max_rounds = request.max_tool_rounds if request.max_tool_rounds is not None else 5

        self._logger.info(
            "Creating chat completion",
            provider_id=str(request.provider_id),
            provider_kind=provider_kind,
            model=request.model,
            tools_count=len(merged_tools) if merged_tools else 0,
            auto_execute_tools=request.auto_execute_tools,
            max_tool_rounds=max_rounds,
        )

        # ---------- 模式一：不自动执行工具，纯透传 LLM ----------
        if not request.auto_execute_tools:
            if provider_kind in self.OPENAI_PROVIDERS:
                return await self._openai_completion(request, provider)
            elif provider_kind == self.ANTHROPIC_PROVIDER:
                return await self._anthropic_completion(request, provider)
            elif provider_kind == self.GOOGLE_PROVIDER:
                return await self._google_completion(request, provider)
            else:
                raise UnsupportedProviderError(provider_kind)

        # ---------- 模式二：自动执行工具 Agent 循环 ----------
        # 实例化工具执行器，注册所有工具
        executor = ToolExecutor(self.db, project_id)
        # 设置插件执行上下文（访客ID、Agent ID等）
        executor.set_context(
            visitor_id=request.user,  # request.user 字段存放 visitor_id
            agent_id=str(request.agent_id) if hasattr(request, "agent_id") else None,
        )
        await executor.register_tools(request.tool_ids, request.collection_ids)

        # 累计 token 使用量，多轮调用累加
        total_usage = Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        # 为什么要调用max_rounds轮？因为工具调用可能会触发大模型生成新的工具调用，形成一个循环，直到没有工具调用为止。为了防止无限循环，我们设置了一个最大轮次限制。
        for round_idx in range(max_rounds):
            self._logger.debug(f"Starting tool round {round_idx + 1}/{max_rounds}")

            # 调用对应后端 LLM
            if provider_kind in self.OPENAI_PROVIDERS:
                response = await self._openai_completion(request, provider)
            elif provider_kind == self.ANTHROPIC_PROVIDER:
                response = await self._anthropic_completion(request, provider)
            elif provider_kind == self.GOOGLE_PROVIDER:
                response = await self._google_completion(request, provider)
            else:
                raise UnsupportedProviderError(provider_kind)

            # 累加 token 用量
            if response.usage:
                total_usage.prompt_tokens += response.usage.prompt_tokens
                total_usage.completion_tokens += response.usage.completion_tokens
                total_usage.total_tokens += response.usage.total_tokens

            # 没有工具调用：对话结束，直接返回
            if not response.choices or not response.choices[0].message.tool_calls:
                response.usage = total_usage
                return response

            # 存在工具调用：提取助手回复与工具调用列表
            assistant_msg_content = response.choices[0].message.content
            tool_calls = response.choices[0].message.tool_calls

            # 将助手回复（含tool_calls）追加到消息历史
            request.messages.append(ChatMessage(
                role="assistant",
                content=assistant_msg_content,
                tool_calls=tool_calls
            ))

            # 并行执行所有工具调用
            execution_tasks = []
            for tc in tool_calls:
                execution_tasks.append(executor.execute(tc.function.name, tc.function.arguments))

            results = await asyncio.gather(*execution_tasks)

            # 将工具执行结果以 role=tool 消息追加到历史
            for tc, result in zip(tool_calls, results):
                request.messages.append(ChatMessage(
                    role="tool",
                    name=tc.function.name,
                    content=result,
                    tool_call_id=tc.id
                ))

            # 进入下一轮 LLM 调用

        # 达到最大轮次仍未结束：移除 tools 约束，做最后一次纯文本生成收尾
        self._logger.warning(f"Reached max tool rounds ({max_rounds}), finishing without tools")
        request.tools = None
        if provider_kind in self.OPENAI_PROVIDERS:
            response = await self._openai_completion(request, provider)
        elif provider_kind == self.ANTHROPIC_PROVIDER:
            response = await self._anthropic_completion(request, provider)
        elif provider_kind == self.GOOGLE_PROVIDER:
            response = await self._google_completion(request, provider)
        else:
            raise UnsupportedProviderError(provider_kind)

        # 累加最后一轮 token
        if response.usage:
            total_usage.prompt_tokens += response.usage.prompt_tokens
            total_usage.completion_tokens += response.usage.completion_tokens
            total_usage.total_tokens += response.usage.total_tokens
        response.usage = total_usage

        return response

    async def create_completion_stream(
        self,
        request: ChatCompletionRequest,
        project_id: uuid.UUID,
    ) -> AsyncIterator[str]:
        """创建 SSE 流式聊天补全，可选开启自动工具调用 Agent 循环。
        返回字符串异步迭代器，每条为标准 SSE `data: {...}\n\n` 格式。
        """
        provider = await self._get_provider(request.provider_id, project_id)
        provider_kind = (provider.provider_kind or "").lower()

        # 合并工具
        merged_tools = await self._merge_tools(request, project_id)
        request.tools = merged_tools

        max_rounds = request.max_tool_rounds if request.max_tool_rounds is not None else 5

        self._logger.info(
            "Creating streaming chat completion",
            provider_id=str(request.provider_id),
            provider_kind=provider_kind,
            model=request.model,
            tools_count=len(merged_tools) if merged_tools else 0,
            auto_execute_tools=request.auto_execute_tools,
            max_tool_rounds=max_rounds,
        )

        # ---------- 模式一：不自动执行工具，直接透传流式响应 ----------
        if not request.auto_execute_tools:
            if provider_kind in self.OPENAI_PROVIDERS:
                stream_gen = self._openai_stream(request, provider)
            elif provider_kind == self.ANTHROPIC_PROVIDER:
                stream_gen = self._anthropic_stream(request, provider)
            elif provider_kind == self.GOOGLE_PROVIDER:
                stream_gen = self._google_stream(request, provider)
            else:
                raise UnsupportedProviderError(provider_kind)

            async for raw_chunk in stream_gen:
                yield raw_chunk
            return

        # ---------- 模式二：流式 Agent 循环 ----------
        executor = ToolExecutor(self.db, project_id)
        await executor.register_tools(request.tool_ids, request.collection_ids)

        for round_idx in range(max_rounds):
            self._logger.debug(f"Starting streaming tool round {round_idx + 1}/{max_rounds}")

            current_tool_calls: Dict[int, Dict[str, Any]] = {}  # 按index拼接流式tool_calls
            current_content = ""  # 拼接本轮助手文本内容

            # 获取对应后端的流生成器
            if provider_kind in self.OPENAI_PROVIDERS:
                stream_gen = self._openai_stream(request, provider)
            elif provider_kind == self.ANTHROPIC_PROVIDER:
                stream_gen = self._anthropic_stream(request, provider)
            elif provider_kind == self.GOOGLE_PROVIDER:
                stream_gen = self._google_stream(request, provider)
            else:
                raise UnsupportedProviderError(provider_kind)

            # 逐块流式输出给前端，同时在后台拼接完整内容与工具调用
            '''
            async for 会自动调用异步迭代器的 __anext__() 方法，每次拿到一个 chunk 就执行一次循环体，直到迭代器抛出 StopAsyncIteration 异常（表示数据流结束），
            循环自动退出。所以你不需要手写 while(true)，它已经内置在 async for 语法糖里了。'''
            async for raw_chunk in stream_gen:
                if raw_chunk == "data: [DONE]\n\n":
                    continue

                yield raw_chunk

                # 解析 chunk，拼接完整 tool_calls 用于下一轮
                if raw_chunk.startswith("data: "):
                    data_str = raw_chunk[6:].strip()
                    # data_str 为 [DONE] 或 JSON 字符串，解析失败不影响流式输出
                    if data_str == "[DONE]":
                        continue
                    try:
                        chunk_data = json.loads(data_str)
                        if chunk_data.get("object") == "chat.completion.chunk":
                            choices = chunk_data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                # 拼接文本内容
                                if delta.get("content"):
                                    current_content += delta["content"]
                                # 按 index 拼接每个 tool_call
                                if delta.get("tool_calls"):
                                    for tc_delta in delta["tool_calls"]:
                                        idx = tc_delta.get("index", 0)
                                        if idx not in current_tool_calls:
                                            current_tool_calls[idx] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                                        if tc_delta.get("id"):
                                            current_tool_calls[idx]["id"] += tc_delta["id"]
                                        if tc_delta.get("function"):
                                            f_delta = tc_delta["function"]
                                            if f_delta.get("name"):
                                                current_tool_calls[idx]["function"]["name"] += f_delta["name"]
                                            if f_delta.get("arguments"):
                                                current_tool_calls[idx]["function"]["arguments"] += f_delta["arguments"]
                    except Exception:
                        # 解析失败不影响流式输出，静默跳过
                        pass

            # 本轮没有工具调用：对话结束
            if not current_tool_calls:
                yield "data: [DONE]\n\n"
                return

            # 组装完整 tool_calls 对象
            final_tool_calls = []
            for idx in sorted(current_tool_calls.keys()):
                tc_info = current_tool_calls[idx]
                final_tool_calls.append(ToolCall(
                    id=tc_info["id"],
                    type="function",
                    function=FunctionCall(
                        name=tc_info["function"]["name"],
                        arguments=tc_info["function"]["arguments"]
                    )
                ))

            # 助手消息写入历史
            request.messages.append(ChatMessage(
                role="assistant",
                content=current_content,
                tool_calls=final_tool_calls
            ))

            # 向前端推送 tool_call 自定义事件
            for tc in final_tool_calls:
                yield f"data: {json.dumps({'type': 'tool_call', 'tool_call': tc.model_dump()}, ensure_ascii=False)}\n\n"

            # 并行执行工具
            execution_tasks = [executor.execute(tc.function.name, tc.function.arguments) for tc in final_tool_calls]
            results = await asyncio.gather(*execution_tasks)

            # 向前端推送 tool_result 事件，并写入消息历史
            for tc, result in zip(final_tool_calls, results):
                yield f"data: {json.dumps({'type': 'tool_result', 'tool_call_id': tc.id, 'result': result}, ensure_ascii=False)}\n\n"
                request.messages.append(ChatMessage(
                    role="tool",
                    name=tc.function.name,
                    content=result,
                    tool_call_id=tc.id
                ))

            # 达到最大轮次，跳出循环
            if round_idx == max_rounds - 1:
                self._logger.warning(f"Reached max tool rounds ({max_rounds}), finishing")
                break

        # 达到最大轮次后：去掉 tools 做最后一次纯文本收尾流式输出
        if current_tool_calls and round_idx == max_rounds - 1:
            request.tools = None
            if provider_kind in self.OPENAI_PROVIDERS:
                stream_gen = self._openai_stream(request, provider)
            elif provider_kind == self.ANTHROPIC_PROVIDER:
                stream_gen = self._anthropic_stream(request, provider)
            elif provider_kind == self.GOOGLE_PROVIDER:
                stream_gen = self._google_stream(request, provider)
            else:
                raise UnsupportedProviderError(provider_kind)

            async for raw_chunk in stream_gen:
                yield raw_chunk
        else:
            yield "data: [DONE]\n\n"

    # -------------------------------------------------------------------------
    # 工具合并逻辑
    # -------------------------------------------------------------------------

    async def _merge_tools(
        self,
        request: ChatCompletionRequest,
        project_id: uuid.UUID,
    ) -> Optional[List[ToolDefinition]]:
        """合并三类工具来源：请求自带tools + 数据库tool_ids + RAG集合collection_ids。
        数据库工具和RAG工具并行加载，减少等待时间。
        """
        import asyncio

        db_tools_task = None
        if request.tool_ids:
            db_tools_task = asyncio.create_task(self._load_tools_from_db(request.tool_ids, project_id))

        rag_tools_task = None
        if request.collection_ids:
            rag_tools_task = asyncio.create_task(self._create_rag_tool_definitions(request.collection_ids, project_id))

        db_tools = await db_tools_task if db_tools_task else []
        rag_tools = await rag_tools_task if rag_tools_task else []

        # 按顺序合并：请求tools在前，数据库工具次之，RAG工具最后
        merged_tools: List[ToolDefinition] = []
        if request.tools:
            merged_tools.extend(request.tools)

        merged_tools.extend(db_tools)
        merged_tools.extend(rag_tools)

        return merged_tools if merged_tools else None

    async def _load_tools_from_db(
        self,
        tool_ids: List[uuid.UUID],
        project_id: uuid.UUID,
    ) -> List[ToolDefinition]:
        """从数据库加载工具记录，转换为 OpenAI 兼容的 ToolDefinition。
        inputSchema 从 tool.config 中读取。
        """
        if not tool_ids:
            return []

        stmt = select(Tool).where(
            and_(
                Tool.id.in_(tool_ids),
                Tool.project_id == project_id,
                Tool.deleted_at.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        tools = result.scalars().all()

        tool_defs = []
        for tool in tools:
            parameters = tool.config.get("inputSchema", {}) if tool.config else {}

            tool_defs.append(
                ToolDefinition(
                    type="function",
                    function=FunctionDefinition(
                        name=tool.name,
                        description=tool.description,
                        parameters=parameters,
                    ),
                )
            )

        return tool_defs

    async def _create_rag_tool_definitions(
        self,
        collection_ids: List[str],
        project_id: uuid.UUID,
    ) -> List[ToolDefinition]:
        """从 RAG 服务批量获取集合信息，生成对应的虚拟检索工具定义。
        RAG 服务不可用时降级为通用描述，不阻塞主流程。
        """
        if not collection_ids:
            return []

        tool_defs = []
        try:
            # 批量获取集合详情
            batch_resp = await rag_service_client.get_collections_batch(
                collection_ids, str(project_id)
            )

            found_collections = {str(c.id): c for c in batch_resp.collections}

            for cid in collection_ids:
                if cid in found_collections:
                    col = found_collections[cid]
                    display_name = col.display_name
                    description = col.description or f"Search in {display_name}"
                else:
                    display_name = f"collection_{cid[:8]}"
                    description = f"Search in collection {cid}"

                # 工具命名规则：rag_search_{collection_id前8位无横线}
                tool_name = f"rag_search_{cid.replace('-', '')[:8]}"
                tool_defs.append(
                    ToolDefinition(
                        type="function",
                        function=FunctionDefinition(
                            name=tool_name,
                            description=f"{description} (Semantically similar search)",
                            parameters={
                                "type": "object",
                                "properties": {
                                    "query": {
                                        "type": "string",
                                        "description": "Natural language search query",
                                    }
                                },
                                "required": ["query"],
                            },
                        ),
                    )
                )
        except Exception as e:
            self._logger.warning("Failed to create RAG tool definitions", error=str(e))
            # 降级：RAG 服务挂了也生成通用工具定义，保证功能可用
            for cid in collection_ids:
                tool_name = f"rag_search_{cid.replace('-', '')[:8]}"
                tool_defs.append(
                    ToolDefinition(
                        type="function",
                        function=FunctionDefinition(
                            name=tool_name,
                            description=f"Search in collection {cid} (Semantically similar search)",
                            parameters={
                                "type": "object",
                                "properties": {
                                    "query": {
                                        "type": "string",
                                        "description": "Natural language search query",
                                    }
                                },
                                "required": ["query"],
                            },
                        ),
                    )
                )

        return tool_defs

    # -------------------------------------------------------------------------
    # 服务商校验
    # -------------------------------------------------------------------------

    async def _get_provider(
        self,
        provider_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> LLMProvider:
        """获取并校验 LLM 服务商：存在性、项目归属、启用状态三层校验。"""
        provider = await self.provider_service.get_provider_by_id(provider_id)

        # 不存在或不属于当前项目
        if not provider or provider.project_id != project_id:
            raise ProviderNotFoundError(provider_id)

        # 已停用
        if not provider.is_active:
            raise ProviderNotActiveError(provider_id)

        return provider

    # -------------------------------------------------------------------------
    # OpenAI / OpenAI 兼容接口实现
    # -------------------------------------------------------------------------

    def _create_openai_client(self, provider: LLMProvider) -> AsyncOpenAI:
        """根据服务商凭据创建 OpenAI 异步客户端。"""
        return AsyncOpenAI(
            api_key=provider.api_key,
            base_url=provider.api_base_url,
            organization=provider.organization,
            timeout=provider.timeout or 60.0,
        )

    async def _openai_completion(
        self,
        request: ChatCompletionRequest,
        provider: LLMProvider,
    ) -> ChatCompletionResponse:
        """调用 OpenAI/兼容接口非流式聊天，转换为内部统一响应格式。"""
        try:
            client = self._create_openai_client(provider)
            params = self._build_openai_params(request)
            response = await client.chat.completions.create(**params)

            return ChatCompletionResponse(
                id=response.id,
                created=response.created,
                model=response.model,
                choices=[
                    Choice(
                        index=choice.index,
                        message=ChoiceMessage(
                            role="assistant",
                            content=choice.message.content,
                            tool_calls=self._convert_openai_tool_calls(choice.message.tool_calls),
                        ),
                        finish_reason=choice.finish_reason,
                    )
                    for choice in response.choices
                ],
                usage=Usage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                ) if response.usage else None,
                system_fingerprint=response.system_fingerprint,
            )
        except Exception as e:
            self._logger.error("OpenAI completion failed", error=str(e))
            raise ChatCompletionError(
                f"OpenAI completion failed: {e}",
                details={"provider_kind": "openai", "model": request.model},
            ) from e

    async def _openai_stream(
        self,
        request: ChatCompletionRequest,
        provider: LLMProvider,
    ) -> AsyncIterator[str]:
        """调用 OpenAI/兼容接口流式聊天，输出标准 SSE 字符串流。
        错误以 SSE error 事件输出，不抛出异常中断流。
        """
        try:
            client = self._create_openai_client(provider)
            params = self._build_openai_params(request)
            params["stream"] = True

            stream = await client.chat.completions.create(**params)

            async for chunk in stream:
                chunk_data = ChatCompletionChunk(
                    id=chunk.id,
                    created=chunk.created,
                    model=chunk.model,
                    choices=[
                        StreamChoice(
                            index=choice.index,
                            delta=DeltaMessage(
                                role=getattr(choice.delta, "role", None),
                                content=getattr(choice.delta, "content", None),
                                tool_calls=self._convert_openai_tool_calls(getattr(choice.delta, "tool_calls", None)),
                            ),
                            finish_reason=choice.finish_reason,
                        )
                        for choice in chunk.choices
                    ],
                    system_fingerprint=chunk.system_fingerprint,
                )
                yield f"data: {chunk_data.model_dump_json()}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            self._logger.error("OpenAI streaming failed", error=str(e))
            yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'api_error'}})}\n\n"

    def _convert_openai_tool_calls(self, openai_tool_calls: Optional[List[Any]]) -> Optional[List[ToolCall]]:
        """将 OpenAI SDK 返回的 tool_calls 转换为内部 ToolCall  schema。
        兼容对象格式和字典格式两种情况（流式chunk通常是字典）。
        """
        if not openai_tool_calls:
            return None

        result = []
        for tc in openai_tool_calls:
            if isinstance(tc, dict):
                tc_index = tc.get("index")
                tc_id = tc.get("id")
                tc_type = tc.get("type", "function")
                func_data = tc.get("function")
                f_name = func_data.get("name") if func_data else None
                f_args = func_data.get("arguments") if func_data else None
            else:
                tc_index = getattr(tc, "index", None)
                tc_id = getattr(tc, "id", None)
                tc_type = getattr(tc, "type", "function")
                func_obj = getattr(tc, "function", None)
                f_name = getattr(func_obj, "name", None) if func_obj else None
                f_args = getattr(func_obj, "arguments", None) if func_obj else None

            result.append(ToolCall(
                index=tc_index,
                id=tc_id,
                type=tc_type,
                function=FunctionCall(
                    name=f_name,
                    arguments=f_args
                )
            ))
        return result if result else None

    def _build_openai_params(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        """从内部请求组装 OpenAI API 参数。"""
        params: Dict[str, Any] = {
            "model": request.model,
            "messages": [self._format_openai_message(msg) for msg in request.messages],
        }

        # 可选参数：非空才加入
        optional_params = {
            "temperature": request.temperature,
            "top_p": request.top_p,
            "n": request.n,
            "max_tokens": request.max_tokens,
            "stop": request.stop,
            "presence_penalty": request.presence_penalty,
            "frequency_penalty": request.frequency_penalty,
            "logit_bias": request.logit_bias,
            "user": request.user,
            "seed": request.seed,
        }

        for key, value in optional_params.items():
            if value is not None:
                params[key] = value

        # 复杂参数
        if request.tools:
            params["tools"] = [tool.model_dump() for tool in request.tools]
        if request.tool_choice is not None:
            params["tool_choice"] = request.tool_choice
        if request.response_format:
            params["response_format"] = request.response_format.model_dump()

        return params

    @staticmethod
    def _format_openai_message(msg: ChatMessage) -> Dict[str, Any]:
        """将单条内部消息格式化为 OpenAI 可接受的字典。"""
        result: Dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.name:
            result["name"] = msg.name
        if msg.tool_calls:
            result["tool_calls"] = [tc.model_dump() for tc in msg.tool_calls]
        if msg.tool_call_id:
            result["tool_call_id"] = msg.tool_call_id
        return result

    # -------------------------------------------------------------------------
    # Anthropic 实现
    # -------------------------------------------------------------------------

    def _create_anthropic_client(self, provider: LLMProvider) -> AsyncAnthropic:
        """根据服务商凭据创建 Anthropic 异步客户端。"""
        return AsyncAnthropic(
            api_key=provider.api_key,
            timeout=provider.timeout or 60.0,
        )

    async def _anthropic_completion(
        self,
        request: ChatCompletionRequest,
        provider: LLMProvider,
    ) -> ChatCompletionResponse:
        """调用 Anthropic 非流式聊天，转换为 OpenAI 兼容响应格式。"""
        try:
            client = self._create_anthropic_client(provider)
            system_prompt, messages = self._convert_to_anthropic_messages(request.messages)
            params = self._build_anthropic_params(request, system_prompt, messages)

            response = await client.messages.create(**params)

            # 拼接所有文本块内容
            content = "".join(block.text for block in response.content if hasattr(block, "text"))
            finish_reason = "stop" if response.stop_reason == "end_turn" else response.stop_reason

            return ChatCompletionResponse(
                id=create_completion_id(),  # 自生成ID，Anthropic 不直接返回 OpenAI 格式 id
                created=int(time.time()),
                model=response.model,
                choices=[
                    Choice(
                        index=0,
                        message=ChoiceMessage(role="assistant", content=content),
                        finish_reason=finish_reason,
                    )
                ],
                usage=Usage(
                    prompt_tokens=response.usage.input_tokens,
                    completion_tokens=response.usage.output_tokens,
                    total_tokens=response.usage.input_tokens + response.usage.output_tokens,
                ),
            )
        except Exception as e:
            self._logger.error("Anthropic completion failed", error=str(e))
            raise ChatCompletionError(
                f"Anthropic completion failed: {e}",
                details={"provider_kind": "anthropic", "model": request.model},
            ) from e

    async def _anthropic_stream(
        self,
        request: ChatCompletionRequest,
        provider: LLMProvider,
    ) -> AsyncIterator[str]:
        """调用 Anthropic 流式聊天，转换为标准 SSE 格式输出。"""
        try:
            client = self._create_anthropic_client(provider)
            system_prompt, messages = self._convert_to_anthropic_messages(request.messages)
            params = self._build_anthropic_params(request, system_prompt, messages)

            completion_id = create_completion_id()
            created = int(time.time())
            first_chunk = True

            async with client.messages.stream(**params) as stream:
                async for text in stream.text_stream:
                    chunk = self._create_stream_chunk(
                        completion_id, created, request.model,
                        content=text, role="assistant" if first_chunk else None,
                    )
                    yield f"data: {chunk.model_dump_json()}\n\n"
                    first_chunk = False

            # 收尾块：带上 finish_reason
            final_chunk = self._create_stream_chunk(
                completion_id, created, request.model, finish_reason="stop"
            )
            yield f"data: {final_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            self._logger.error("Anthropic streaming failed", error=str(e))
            yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'api_error'}})}\n\n"

    def _build_anthropic_params(
        self,
        request: ChatCompletionRequest,
        system_prompt: Optional[str],
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """组装 Anthropic API 请求参数。"""
        params: Dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,  # Anthropic 必填 max_tokens
        }

        if system_prompt:
            params["system"] = system_prompt
        if request.temperature is not None:
            params["temperature"] = request.temperature
        if request.top_p is not None:
            params["top_p"] = request.top_p
        if request.stop:
            params["stop_sequences"] = request.stop if isinstance(request.stop, list) else [request.stop]

        # 工具转换为 Anthropic 格式
        if request.tools:
            anthropic_tools = []
            for tool in request.tools:
                if tool.type == "function":
                    anthropic_tools.append({
                        "name": tool.function.name,
                        "description": tool.function.description or "",
                        "input_schema": tool.function.parameters or {"type": "object", "properties": {}},
                    })
            if anthropic_tools:
                params["tools"] = anthropic_tools

        return params

    @staticmethod
    def _convert_to_anthropic_messages(
        messages: List[ChatMessage],
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        """将 OpenAI 格式消息转换为 Anthropic 格式。
        Anthropic 把 system 单独作为参数，不放在 messages 数组里。
        """
        system_prompt = None
        anthropic_messages = []

        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content
            elif msg.role in ("user", "assistant"):
                anthropic_messages.append({"role": msg.role, "content": msg.content or ""})

        return system_prompt, anthropic_messages

    # -------------------------------------------------------------------------
    # Google Gemini 实现
    # -------------------------------------------------------------------------

    @staticmethod
    def _configure_gemini(api_key: str) -> None:
        """配置 Gemini API 密钥（全局配置）。"""
        genai.configure(api_key=api_key)

    async def _google_completion(
        self,
        request: ChatCompletionRequest,
        provider: LLMProvider,
    ) -> ChatCompletionResponse:
        """调用 Google Gemini 非流式聊天，转换为 OpenAI 兼容格式。
        注意：Gemini token 用量为按词数估算值，非精确计费 token。
        """
        try:
            self._configure_gemini(provider.api_key)

            # 工具转换为 Gemini function_declarations 格式
            tools = None
            if request.tools:
                gemini_functions = []
                for tool in request.tools:
                    if tool.type == "function":
                        gemini_functions.append({
                            "name": tool.function.name,
                            "description": tool.function.description or "",
                            "parameters": tool.function.parameters or {"type": "object", "properties": {}},
                        })
                if gemini_functions:
                    tools = [{"function_declarations": gemini_functions}]

            model = genai.GenerativeModel(request.model, tools=tools)
            history, last_message = self._convert_to_gemini_messages(request.messages)
            generation_config = self._build_gemini_config(request)

            chat = model.start_chat(history=history)
            response = await chat.send_message_async(
                last_message,
                generation_config=generation_config or None,
            )

            content = response.text
            # 粗略估算 token：按空格分词数估算
            prompt_tokens = sum(len(str(m.get("parts", [""])[0]).split()) for m in history) + len(last_message.split())
            completion_tokens = len(content.split())

            return ChatCompletionResponse(
                id=create_completion_id(),
                created=int(time.time()),
                model=request.model,
                choices=[
                    Choice(
                        index=0,
                        message=ChoiceMessage(role="assistant", content=content),
                        finish_reason="stop",
                    )
                ],
                usage=Usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                ),
            )
        except Exception as e:
            self._logger.error("Google completion failed", error=str(e))
            raise ChatCompletionError(
                f"Google completion failed: {e}",
                details={"provider_kind": "google", "model": request.model},
            ) from e

    async def _google_stream(
        self,
        request: ChatCompletionRequest,
        provider: LLMProvider,
    ) -> AsyncIterator[str]:
        """调用 Google Gemini 流式聊天，输出标准 SSE 格式。"""
        try:
            self._configure_gemini(provider.api_key)

            tools = None
            if request.tools:
                gemini_functions = []
                for tool in request.tools:
                    if tool.type == "function":
                        gemini_functions.append({
                            "name": tool.function.name,
                            "description": tool.function.description or "",
                            "parameters": tool.function.parameters or {"type": "object", "properties": {}},
                        })
                if gemini_functions:
                    tools = [{"function_declarations": gemini_functions}]

            model = genai.GenerativeModel(request.model, tools=tools)
            history, last_message = self._convert_to_gemini_messages(request.messages)
            generation_config = self._build_gemini_config(request)

            chat = model.start_chat(history=history)
            completion_id = create_completion_id()
            created = int(time.time())
            first_chunk = True

            response = await chat.send_message_async(
                last_message,
                generation_config=generation_config or None,
                stream=True,
            )

            async for chunk in response:
                if chunk.text:
                    stream_chunk = self._create_stream_chunk(
                        completion_id, created, request.model,
                        content=chunk.text, role="assistant" if first_chunk else None,
                    )
                    yield f"data: {stream_chunk.model_dump_json()}\n\n"
                    first_chunk = False

            # 收尾块
            final_chunk = self._create_stream_chunk(
                completion_id, created, request.model, finish_reason="stop"
            )
            yield f"data: {final_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            self._logger.error("Google streaming failed", error=str(e))
            yield f"data: {json.dumps({'error': {'message': str(e), 'type': 'api_error'}})}\n\n"

    @staticmethod
    def _build_gemini_config(request: ChatCompletionRequest) -> Dict[str, Any]:
        """组装 Gemini 生成配置参数。"""
        config: Dict[str, Any] = {}
        if request.temperature is not None:
            config["temperature"] = request.temperature
        if request.top_p is not None:
            config["top_p"] = request.top_p
        if request.max_tokens is not None:
            config["max_output_tokens"] = request.max_tokens
        if request.stop:
            config["stop_sequences"] = request.stop if isinstance(request.stop, list) else [request.stop]
        return config

    @staticmethod
    def _convert_to_gemini_messages(
        messages: List[ChatMessage],
    ) -> tuple[List[Dict[str, Any]], str]:
        """将 OpenAI 格式消息转换为 Gemini 格式：历史消息列表 + 最后一条用户消息。
        system 指令不单独支持，拼接到最后一条用户消息前面。
        """
        history: List[Dict[str, Any]] = []
        last_message = ""
        system_instruction = None

        for i, msg in enumerate(messages):
            if msg.role == "system":
                system_instruction = msg.content
            elif msg.role == "user":
                if i == len(messages) - 1:
                    last_message = msg.content or ""
                else:
                    history.append({"role": "user", "parts": [msg.content or ""]})
            elif msg.role == "assistant":
                history.append({"role": "model", "parts": [msg.content or ""]})

        # system 指令拼接到最后一条用户消息
        if system_instruction:
            last_message = f"{system_instruction}\n\n{last_message}" if last_message else system_instruction

        return history, last_message

    # -------------------------------------------------------------------------
    # 通用辅助方法
    # -------------------------------------------------------------------------

    @staticmethod
    def _create_stream_chunk(
        completion_id: str,
        created: int,
        model: str,
        content: Optional[str] = None,
        role: Optional[str] = None,
        finish_reason: Optional[str] = None,
    ) -> ChatCompletionChunk:
        """构造一个标准流式响应块。"""
        return ChatCompletionChunk(
            id=completion_id,
            created=created,
            model=model,
            choices=[
                StreamChoice(
                    index=0,
                    delta=DeltaMessage(role=role, content=content),
                    finish_reason=finish_reason,
                )
            ],
        )