"""Service for managing LLM Provider credentials (synced from tgo-api).
# LLM大模型服务商凭证业务服务层
# 负责LLMProvider数据库模型的增删改查、批量同步逻辑；数据来源是外部tgo‑api，会把服务商配置同步到本地库
# 同时级联同步该服务商下属的LLMModel模型列表，不在同步载荷内的模型会被软停用
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_provider import LLMProvider
from app.models.llm_model import LLMModel


class LLMProviderService:
    """Application service for LLMProvider CRUD and sync operations.
    # LLM服务商业务服务类
    # 依赖注入AsyncSession会话，所有数据库操作复用同一个db会话；提供单条CRUD + 批量同步能力
    """

    def __init__(self, db: AsyncSession) -> None:
        """接收数据库异步会话，服务实例绑定该db会话"""
        self.db = db

    async def list_providers(
        self,
        project_id: uuid.UUID,
        include_inactive: bool = False,
    ) -> List[LLMProvider]:
        """
        查询指定项目下全部LLM服务商
        :param project_id: 项目UUID，租户隔离
        :param include_inactive: 是否包含已停用的服务商，默认只查active=True
        :return: LLMProvider ORM对象列表
        """
        # 基础查询：筛选项目
        stmt = select(LLMProvider).where(LLMProvider.project_id == project_id)
        # 如果不包含停用，追加is_active=True条件
        if not include_inactive:
            stmt = stmt.where(LLMProvider.is_active.is_(True))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_provider_by_id(
        self,
        provider_id: uuid.UUID | str,
    ) -> Optional[LLMProvider]:
        """Get provider by primary key ID.
        根据主键ID查询单个服务商，支持传入字符串UUID自动转换
        :param provider_id: 服务商主键ID，字符串/UUID对象都支持
        :return: ORM实例，找不到返回None
        """
        # 如果传入字符串，转成uuid.UUID对象，适配SQLAlchemy字段类型
        if isinstance(provider_id, str):
            provider_id = uuid.UUID(provider_id)
        stmt = select(LLMProvider).where(LLMProvider.id == provider_id)
        result = await self.db.execute(stmt)
        # scalar_one_or_none：找到返回实例，无数据返回None，多条抛异常（id为主键不会多条）
        return result.scalar_one_or_none()

    async def get_providers_by_alias(
        self,
        project_id: uuid.UUID | str,
        alias: str,
    ) -> List[LLMProvider]:
        """Get providers by project_id and alias (may return multiple).
        根据项目+别名alias查询服务商；同一个项目下alias允许多条，返回列表
        :param project_id: 项目ID，支持字符串/UUID
        :param alias: 服务商别名，业务侧自定义标识
        :return: 匹配的服务商ORM列表
        """
        if isinstance(project_id, str):
            project_id = uuid.UUID(project_id)
        stmt = select(LLMProvider).where(
            LLMProvider.project_id == project_id,
            LLMProvider.alias == alias,
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def upsert_provider(
        self,
        project_id: uuid.UUID | str,
        *,
        provider_id: uuid.UUID | str,
        alias: str,
        provider_kind: str,
        vendor: Optional[str] = None,
        api_base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        organization: Optional[str] = None,
        timeout: Optional[float] = None,
        is_active: bool = True,
    ) -> LLMProvider:
        """Create or update a provider by ID (primary key).
        单条upsert：根据主键provider_id，存在则更新，不存在则新建
        注意api_key特殊逻辑：只有入参显式传入api_key才覆盖，入参为None不会清空数据库原有密钥
        :param project_id: 所属项目ID
        :param provider_id: 服务商主键ID，作为upsert判断依据
        :param alias: 业务别名
        :param provider_kind: 服务商类型
        :param vendor: 厂商名称
        :param api_base_url: API代理地址
        :param api_key: 密钥，None代表不更新密钥
        :param default_model: 默认模型名
        :param organization: 组织字段（openai‑organization）
        :param timeout: 请求超时时间
        :param is_active: 是否启用
        :return: 更新/新建完成后的ORM对象
        """
        # 字符串ID转UUID对象
        if isinstance(project_id, str):
            project_id = uuid.UUID(project_id)
        if isinstance(provider_id, str):
            provider_id = uuid.UUID(provider_id)

        existing = await self.get_provider_by_id(provider_id)
        now = datetime.now(timezone.utc)

        if existing:
            # -------- 更新已有记录 --------
            existing.project_id = project_id
            existing.alias = alias
            existing.provider_kind = provider_kind
            existing.vendor = vendor
            existing.api_base_url = api_base_url
            # 核心逻辑：只有api_key不为None才覆盖；partial更新场景不会把数据库密钥置空
            if api_key is not None:
                existing.api_key = api_key
            existing.default_model = default_model
            existing.organization = organization
            existing.timeout = timeout
            existing.is_active = is_active
            existing.synced_at = now  # 更新同步时间戳，标记数据来自外部同步
            await self.db.flush()       # flush刷到会话，不commit，还在事务内
            await self.db.refresh(existing) # 刷新对象，拿到数据库最新状态
            return existing

        # -------- 创建新记录 --------
        provider = LLMProvider(
            id=provider_id,
            project_id=project_id,
            alias=alias,
            provider_kind=provider_kind,
            vendor=vendor,
            api_base_url=api_base_url,
            api_key=api_key,
            default_model=default_model,
            organization=organization,
            timeout=timeout,
            is_active=is_active,
            synced_at=now,
        )
        self.db.add(provider)
        await self.db.flush()
        await self.db.refresh(provider)
        return provider

    async def deactivate_provider(
        self,
        provider_id: uuid.UUID,
    ) -> None:
        """Deactivate a provider by ID.
        软停用服务商：不会物理删除，设置is_active=False，更新synced_at
        """
        provider = await self.get_provider_by_id(provider_id)
        if provider:
            provider.is_active = False
            provider.synced_at = datetime.now(timezone.utc)
            await self.db.flush()
    # sync_providers 是从外部数据源（tgo‑api）批量同步 LLM 服务商配置到本地数据库的原子批量同步入口函数，实现「外部权威数据源驱动本地状态」，整套操作在同一个数据库事务内。
    # 根据外部权威数据源批量新增 / 更新服务商，同时同步它下属模型，不在推送载荷里的旧模型自动软停用；要么全部同步成功，要么全部回滚。
    async def sync_providers(
        self,
        providers: Iterable[dict],
    ) -> List[LLMProvider]:
        """Bulk upsert providers.
        # 批量同步服务商（外部tgo‑api推送过来的数据）
        1. 遍历每一条payload，按provider_id做upsert（新建或更新）
        2. 如果payload携带models数组，级联同步下属LLMModel模型
        3. 该服务商下，不在本次同步载荷里的模型，设置is_active=False软停用
        4. 全部成功则commit；任意异常执行rollback，全部回滚，保证事务原子性

        For each incoming item (must include id, project_id and alias), update if exists else create.
        Uses provider ID as the primary key for upsert logic.

        :param providers: 外部传入的服务商字典迭代器，每条必须包含id、project_id、alias
        :return: 同步完成的LLMProvider ORM列表
        """
        synced: list[LLMProvider] = []
        try:
            for payload in providers:
                project_id = payload["project_id"]
                alias = payload["alias"].strip() # 去除别名前后空格
                # 单条upsert服务商主记录
                provider = await self.upsert_provider(
                    project_id,
                    provider_id=payload["id"],
                    alias=alias,
                    provider_kind=payload["provider_kind"],
                    vendor=payload.get("vendor"),
                    api_base_url=payload.get("api_base_url"),
                    api_key=payload.get("api_key"),
                    default_model=payload.get("default_model"),
                    organization=payload.get("organization"),
                    timeout=payload.get("timeout"),
                    is_active=payload.get("is_active", True),
                )
                # -------- 级联同步下属模型models --------
                if payload.get("models") is not None:
                    # 局部导入，避免循环import（LLMModelService内部可能又引用本service）
                    from app.services.llm_model_service import LLMModelService
                    model_service = LLMModelService(self.db)
                    models_to_sync = []
                    for m_payload in payload["models"]:
                        # 兼容两种入参：dict字典 或者 Pydantic模型对象，统一转为dict
                        m_dict = m_payload if isinstance(m_payload, dict) else m_payload.model_dump()
                        # 强制绑定当前provider_id，防止外部payload传错归属
                        m_dict["provider_id"] = provider.id
                        models_to_sync.append(m_dict)

                    # 同步模型，commit=False：不在这里提交，交给外层统一commit
                    await model_service.sync_models(models_to_sync, commit=False)

                    # 将本次同步的模型ID收集起来
                    synced_model_ids = [m["id"] for m in models_to_sync]
                    # 该provider下，ID不在本次同步列表中的模型 → 软停用
                    await self.db.execute(
                        update(LLMModel)
                        .where(LLMModel.provider_id == provider.id)
                        .where(LLMModel.id.notin_(synced_model_ids))
                        .values(is_active=False, synced_at=datetime.now(timezone.utc))
                    )

                synced.append(provider)
            # 全部循环执行完成，统一提交事务
            await self.db.commit()
            return synced
        except Exception:
            # 任何异常，整个批量同步全部回滚，避免部分写入
            await self.db.rollback()
            raise