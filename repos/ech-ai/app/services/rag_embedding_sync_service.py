"""将嵌入模型配置从 tgo‑ai 同步至 tgo‑rag，支持失败重试。

该服务基于 ProjectAIConfig 与 LLMProvider 组装请求载荷，
调用 app.services.rag_service 向 RAG 服务发起批量同步请求。

设计要点：
- 全部载荷在当前数据库会话中预先组装完成。
- 网络请求在后台任务执行，**不复用请求上下文的数据库会话**。
- 采用指数退避重试策略（默认 1秒、2秒、4秒），发生错误仅打日志不向上抛出。
- 更新 ProjectAIConfig 的同步状态字段，记录 pending/success/failed 状态以及重试次数。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database import AsyncSessionLocal
from app.models.llm_provider import LLMProvider
from app.models.project_ai_config import ProjectAIConfig
from app.services.rag_service import (
    EmbeddingConfigCreate,
    EmbeddingConfigBatchSyncResponse,
    rag_service_client,
)


logger = get_logger("services.rag_embedding_sync")


def _map_provider_for_rag(provider_kind: str, vendor: Optional[str]) -> Optional[str]:
    """内部服务商类型/厂商映射为RAG服务可识别的provider枚举。

    根据RAG侧OpenAPI文档支持取值："openai", "qwen3"。
    """
    kind = (provider_kind or "").lower()
    vend = (vendor or "").lower() if vendor else None

    if kind == "openai":
        return "openai"
    # Qwen3 兼容OpenAI接口；依靠vendor字段区分
    if kind in ("openai_compatible", "openai-compatible", "openai compatible") and vend in {"qwen3", "qwen"}:
        return "qwen3"

    return None


async def build_embedding_configs(
    db: AsyncSession,
    cfgs: Iterable[ProjectAIConfig],
) -> List[EmbeddingConfigCreate]:
    """根据 ProjectAIConfig 记录组装 EmbeddingConfigCreate 请求载荷。

    跳过缺少嵌入模型配置、或者服务商无法映射的条目。
    """
    payloads: List[EmbeddingConfigCreate] = []
    for cfg in cfgs:
        if not cfg.default_embedding_provider_id or not cfg.default_embedding_model:
            # 当前项目无嵌入模型配置，无需同步
            continue

        # 根据ID查询服务商凭据信息
        stmt = select(LLMProvider).where(LLMProvider.id == cfg.default_embedding_provider_id)
        res = await db.execute(stmt)
        provider: Optional[LLMProvider] = res.scalar_one_or_none()
        if not provider or not provider.is_active:
            logger.warning(
                "跳过嵌入配置同步：服务商不存在或已停用",
                project_id=str(cfg.project_id),
                provider_id=str(cfg.default_embedding_provider_id) if cfg.default_embedding_provider_id else None,
            )
            continue

        provider_name = provider.provider_kind

        payloads.append(
            EmbeddingConfigCreate(
                project_id=cfg.project_id,
                provider=provider_name,
                model=cfg.default_embedding_model,
                # dimensions、batch_size 使用RAG服务端默认值
                api_key=provider.api_key,
                base_url=provider.api_base_url,
                is_active=True,
            )
        )

    return payloads


async def dispatch_to_rag_with_retry(
    configs: List[EmbeddingConfigCreate],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> Optional[EmbeddingConfigBatchSyncResponse]:
    """向RAG服务发送配置，带指数退避有限次重试。

    成功返回RAG响应对象；重试耗尽返回None。
    捕获全部异常并打日志，防止后台任务崩溃。
    """
    if not configs:
        return EmbeddingConfigBatchSyncResponse(success_count=0, failed_count=0, errors=[])

    # 仅负责网络调用；数据库状态更新由后台任务上层处理
    attempt = 0
    while True:
        try:
            resp = await rag_service_client.batch_sync_embedding_configs(configs)
            logger.info(
                "嵌入模型配置已同步至RAG服务",
                success_count=resp.success_count,
                failed_count=resp.failed_count,
            )
            return resp
        except Exception as e:  # noqa: BLE001 后台任务刻意使用大范围捕获
            attempt += 1
            if attempt >= max_retries:
                logger.error(
                    "嵌入配置同步已用尽重试次数，同步失败",
                    error=str(e),
                    attempts=attempt,
                )
                return None
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "嵌入配置同步尝试失败，即将重试",
                attempt=attempt,
                delay_seconds=delay,
                error=str(e),
            )
            await asyncio.sleep(delay)


def fire_and_forget_embedding_sync(configs: List[EmbeddingConfigCreate]) -> None:
    """调度后台异步同步任务，调用方不会抛出异常。

    维护 ProjectAIConfig 同步生命周期字段：
    - 任务启动标记为 pending（**不重置累计重试次数**，多次同步会累加计数）
    - 每次重试递增尝试次数
    - 同步成功更新 last_sync_at 时间戳，状态置 success
    - 重试全部失败后标记 failed，并记录错误信息
    """

    async def _runner() -> None:
        from sqlalchemy import select
        project_ids = [c.project_id for c in configs]
        if not project_ids:
            return

        async with AsyncSessionLocal() as session:
            try:
                # 设置状态为pending，清空旧错误；保留原有重试计数
                res = await session.execute(select(ProjectAIConfig).where(ProjectAIConfig.project_id.in_(project_ids)))
                rows = res.scalars().all()
                for r in rows:
                    r.sync_status = "pending"
                    r.sync_error = None
                await session.commit()

                attempt = 0
                max_retries = 3
                base_delay = 1.0
                while True:
                    attempt += 1
                    # 递增同步尝试次数
                    res = await session.execute(select(ProjectAIConfig).where(ProjectAIConfig.project_id.in_(project_ids)))
                    rows = res.scalars().all()
                    for r in rows:
                        r.sync_attempt_count = (r.sync_attempt_count or 0) + 1
                    await session.commit()

                    try:
                        resp = await rag_service_client.batch_sync_embedding_configs(configs)
                        # 同步成功：更新状态与最后同步时间
                        now = datetime.now(timezone.utc)
                        res = await session.execute(select(ProjectAIConfig).where(ProjectAIConfig.project_id.in_(project_ids)))
                        rows = res.scalars().all()
                        for r in rows:
                            r.sync_status = "success"
                            r.sync_error = None
                            r.last_sync_at = now
                        await session.commit()
                        logger.info(
                            "嵌入模型配置同步完成",
                            success_count=getattr(resp, "success_count", None),
                            failed_count=getattr(resp, "failed_count", None),
                        )
                        break
                    except Exception as e:  # noqa: BLE001
                        if attempt >= max_retries:
                            # 全部重试耗尽，标记失败并保存错误
                            res = await session.execute(select(ProjectAIConfig).where(ProjectAIConfig.project_id.in_(project_ids)))
                            rows = res.scalars().all()
                            for r in rows:
                                r.sync_status = "failed"
                                r.sync_error = str(e)
                            await session.commit()
                            logger.error("嵌入配置同步重试耗尽，最终失败", error=str(e), attempts=attempt)
                            break
                        delay = base_delay * (2 ** (attempt - 1))
                        logger.warning("嵌入配置同步尝试失败，准备重试", attempt=attempt, delay_seconds=delay, error=str(e))
                        await asyncio.sleep(delay)
            except Exception as e:  # pragma: no cover 防御性兜底捕获
                # 兜底捕获后台任务异常，避免未处理异常丢失
                logger.error("嵌入配置同步后台任务发生崩溃", error=str(e))

    # 在当前事件循环调度后台任务
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_runner())
    except RuntimeError:
        # 无运行中事件循环（FastAPI场景极少出现），同步执行
        asyncio.run(_runner())