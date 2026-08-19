"""Service for managing LLM Model metadata (synced from tgo-api).
# LLM模型元数据业务服务层
# 管理LLMModel表：存储每个服务商下具体大模型的元信息（模型标识、上下文窗口、能力、状态等）
# 数据来源外部 tgo‑api，提供单条CRUD、upsert、批量同步能力；和 LLMProviderService 配合使用
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_model import LLMModel


class LLMModelService:
    """Application service for LLMModel CRUD and sync operations.
    # LLM模型业务服务类
    # 绑定数据库异步会话AsyncSession，完成模型的查询、新建、更新、批量同步、软停用
    """

    def __init__(self, db: AsyncSession) -> None:
        """注入数据库异步会话，后续所有数据库操作复用该会话"""
        self.db = db

    async def list_models(
        self,
        provider_id: Optional[uuid.UUID] = None,
        model_type: Optional[str] = None,
        include_inactive: bool = False,
    ) -> List[LLMModel]:
        """
        查询模型列表，支持多条件过滤
        :param provider_id: 服务商ID，过滤属于该服务商下的模型；不传查全部服务商
        :param model_type: 模型类型，例如 chat / embedding；不传不做类型过滤
        :param include_inactive: 是否返回已停用(is_active=False)的模型；默认只返回启用状态
        :return: LLMModel ORM对象列表
        """
        stmt = select(LLMModel)
        # 按服务商过滤
        if provider_id:
            stmt = stmt.where(LLMModel.provider_id == provider_id)
        # 按模型类型过滤
        if model_type:
            stmt = stmt.where(LLMModel.model_type == model_type)
        # 默认只查询启用状态的模型
        if not include_inactive:
            stmt = stmt.where(LLMModel.is_active.is_(True))

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_model_by_id(
        self,
        model_id: uuid.UUID | str,
    ) -> Optional[LLMModel]:
        """Get model by primary key ID.
        根据主键ID查询单条模型记录；支持字符串格式的UUID自动转换
        :param model_id: 模型主键ID，字符串 / UUID对象
        :return: ORM实例，找不到返回None
        """
        if isinstance(model_id, str):
            model_id = uuid.UUID(model_id)
        stmt = select(LLMModel).where(LLMModel.id == model_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_model(
        self,
        *,
        id: uuid.UUID | str,
        provider_id: uuid.UUID | str,
        model_id: str,
        model_name: str,
        model_type: str = "chat",
        description: Optional[str] = None,
        capabilities: Optional[dict] = None,
        context_window: Optional[int] = None,
        max_tokens: Optional[int] = None,
        is_active: bool = True,
        store_resource_id: Optional[str] = None,
    ) -> LLMModel:
        """Create or update a model by ID (primary key).
        # 模型单条upsert：存在更新，不存在新建
        # 重要兼容逻辑：优先按主键id查找；找不到再按 (provider_id + model_id) 联合查找，用来规避唯一键冲突
        :param id: 模型全局主键UUID
        :param provider_id: 所属服务商主键ID
        :param model_id: 模型对外标识字符串，例如 qwen‑plus，同一个provider下不能重复
        :param model_name: 模型展示名称
        :param model_type: 模型类型，默认chat对话模型
        :param description: 模型描述
        :param capabilities: 模型能力字典，例如支持function_call、vision等
        :param context_window: 上下文窗口总token数
        :param max_tokens: 最大输出token
        :param is_active: 是否启用
        :param store_resource_id: 资源存储ID
        :return: 更新/新建完成后的ORM对象
        """
        # 字符串ID转为UUID对象适配数据库字段
        if isinstance(id, str):
            id = uuid.UUID(id)
        if isinstance(provider_id, str):
            provider_id = uuid.UUID(provider_id)

        now = datetime.now(timezone.utc)

        # 1. 优先使用全局主键id查询记录
        existing = await self.get_model_by_id(id)

        # 2. 如果按主键找不到，再用联合唯一键查询：provider_id + model_id，并且排除逻辑删除(deleted_at不为空)的数据
        # 业务背景：外部同步推送可能主键id发生变化，但(provider_id,model_id)不变，防止数据库唯一约束报错
        if not existing:
            stmt = select(LLMModel).where(
                LLMModel.provider_id == provider_id,
                LLMModel.model_id == model_id,
                LLMModel.deleted_at.is_(None)
            )
            result = await self.db.execute(stmt)
            existing = result.scalar_one_or_none()

        if existing:
            # -------- 更新已有记录 --------
            # 即使传入的id和数据库现存主键id不一致，仍然复用数据库现存对象id，避免主键冲突
            existing.provider_id = provider_id
            existing.model_id = model_id
            existing.model_name = model_name
            existing.model_type = model_type
            existing.description = description
            existing.capabilities = capabilities
            existing.context_window = context_window
            existing.max_tokens = max_tokens
            existing.is_active = is_active
            existing.store_resource_id = store_resource_id
            existing.synced_at = now  # 更新同步时间戳，标记来自外部同步
            await self.db.flush()
            await self.db.refresh(existing)
            return existing

        # -------- 创建新记录 --------
        model = LLMModel(
            id=id,
            provider_id=provider_id,
            model_id=model_id,
            model_name=model_name,
            model_type=model_type,
            description=description,
            capabilities=capabilities,
            context_window=context_window,
            max_tokens=max_tokens,
            is_active=is_active,
            store_resource_id=store_resource_id,
            synced_at=now,
        )
        self.db.add(model)
        await self.db.flush()
        await self.db.refresh(model)
        return model

    async def sync_models(
        self,
        models: Iterable[dict],
        commit: bool = True,
    ) -> List[LLMModel]:
        """Bulk upsert models.
        # 批量upsert模型列表
        Uses model ID as the primary key for upsert logic.
        :param models: 待同步的模型字典迭代器，每条payload必须包含id、provider_id、model_id、model_name
        :param commit: 是否执行db.commit()；False代表交给外层事务统一提交（LLMProviderService调用时传False）
        :return: 同步完成的ORM对象列表
        """
        synced: list[LLMModel] = []
        for payload in models:
            model = await self.upsert_model(
                id=payload["id"],
                provider_id=payload["provider_id"],
                model_id=payload["model_id"],
                model_name=payload["model_name"],
                model_type=payload.get("model_type", "chat"),
                description=payload.get("description"),
                capabilities=payload.get("capabilities"),
                context_window=payload.get("context_window"),
                max_tokens=payload.get("max_tokens"),
                is_active=payload.get("is_active", True),
                store_resource_id=payload.get("store_resource_id"),
            )
            synced.append(model)
        # commit=True才提交；外层调用方（LLMProviderService）会关闭提交，由外层统一commit保证事务
        if commit:
            await self.db.commit()
        return synced

    async def deactivate_model(
        self,
        model_pk: uuid.UUID,
    ) -> None:
        """Deactivate a model by ID.
        软停用模型，不物理删除记录，设置is_active=False并更新同步时间
        """
        model = await self.get_model_by_id(model_pk)
        if model:
            model.is_active = False
            model.synced_at = datetime.now(timezone.utc)
            await self.db.flush()