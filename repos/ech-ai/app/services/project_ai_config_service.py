"""Service for syncing project‑level default AI model configs from tgo‑api.
项目AI模型配置服务：负责同步来自tgo‑api的项目级默认AI模型配置。
每个项目保存一套默认聊天模型、嵌入模型配置；配置变更后触发RAG嵌入后台同步任务。
"""

from __future__ import annotations

import uuid
from typing import Iterable, List, Optional

from sqlalchemy import select
# SQLAlchemy异步会话，数据库操作上下文
from sqlalchemy.ext.asyncio import AsyncSession

# ORM数据库模型：项目AI配置表，存储每个项目默认chat/embedding模型
from app.models.project_ai_config import ProjectAIConfig
# RAG嵌入同步相关工具：组装嵌入配置、触发“发后即忘”后台异步同步任务
from app.services.rag_embedding_sync_service import (
    build_embedding_configs,
    fire_and_forget_embedding_sync,
)


class ProjectAIConfigService:
    """应用层业务服务：负责 ProjectAIConfig 的查询、新增/更新(upsert)逻辑。
    每个项目会保存一套默认AI模型配置：聊天模型、嵌入模型。
    配置发生变更后，会触发RAG向量库的嵌入模型同步后台任务。
    """

    def __init__(self, db: AsyncSession) -> None:
        """
        :param db: SQLAlchemy异步数据库会话，由上层依赖注入传入
        """
        self.db = db

    async def get(self, project_id: uuid.UUID) -> Optional[ProjectAIConfig]:
        """根据项目ID查询项目AI模型配置。
        :param project_id: 项目唯一ID
        :return: 存在返回ORM实例，不存在返回 None
        """
        # 构造select查询语句，按project_id过滤
        stmt = select(ProjectAIConfig).where(ProjectAIConfig.project_id == project_id)
        res = await self.db.execute(stmt)
        # 返回最多一条记录，无结果返回None
        return res.scalar_one_or_none()

    async def upsert_config(
        self,
        *,
        project_id: uuid.UUID,
        default_chat_provider_id: Optional[uuid.UUID] = None,
        default_chat_model: Optional[str] = None,
        default_embedding_provider_id: Optional[uuid.UUID] = None,
        default_embedding_model: Optional[str] = None,
    ) -> ProjectAIConfig:
        """
        新增或者更新单个项目AI配置（upsert语义）。
        如果记录已存在：覆盖字段，重置同步状态为pending，清空错误、重置重试次数。
        如果记录不存在：新建一条ProjectAIConfig记录。
        数据库commit之后，触发**发后即忘**的RAG嵌入同步后台任务。

        命名参数调用，必须使用关键字传参。

        :param project_id: 项目ID
        :param default_chat_provider_id: 默认聊天模型服务商ID
        :param default_chat_model: 默认聊天模型名称字符串
        :param default_embedding_provider_id: 默认嵌入模型服务商ID
        :param default_embedding_model: 默认嵌入模型名称字符串
        :return: 数据库ORM实例（已刷新，具备数据库生成字段）
        """
        # 查询该项目已有配置
        existing = await self.get(project_id)
        if existing:
            # 记录已存在，执行更新逻辑：覆盖各个模型配置字段
            existing.default_chat_provider_id = default_chat_provider_id
            existing.default_chat_model = default_chat_model
            existing.default_embedding_provider_id = default_embedding_provider_id
            existing.default_embedding_model = default_embedding_model

            # 重置同步状态：标记为待同步pending，清空错误信息，重置重试计数
            # 嵌入模型发生变更，需要重新执行向量库同步
            existing.sync_status = "pending"
            existing.sync_error = None
            existing.sync_attempt_count = 0

            # flush：把对象变更刷到会话，尚未提交数据库
            await self.db.flush()
            # refresh：从数据库刷新实例，获取数据库侧最新状态
            await self.db.refresh(existing)
            # 执行commit，持久化；必须commit，保证后台任务的数据库会话可以读到这条变更
            await self.db.commit()

            # 组装嵌入同步配置，触发fire‑and‑forget后台任务（不等待任务执行完成）
            configs = await build_embedding_configs(self.db, [existing])
            if configs:
                fire_and_forget_embedding_sync(configs)
            return existing

        # 该项目没有配置：新建ProjectAIConfig数据库记录
        cfg = ProjectAIConfig(
            project_id=project_id,
            default_chat_provider_id=default_chat_provider_id,
            default_chat_model=default_chat_model,
            default_embedding_provider_id=default_embedding_provider_id,
            default_embedding_model=default_embedding_model,
            sync_status="pending",
            sync_error=None,
            sync_attempt_count=0,
        )
        # 将对象加入db会话
        self.db.add(cfg)
        await self.db.flush()
        await self.db.refresh(cfg)
        await self.db.commit()  # 提交，让后台任务会话可见

        # 触发嵌入模型同步后台任务
        configs = await build_embedding_configs(self.db, [cfg])
        if configs:
            fire_and_forget_embedding_sync(configs)
        return cfg

    async def sync_configs(self, configs: Iterable[dict]) -> List[ProjectAIConfig]:
        """批量同步多个项目的AI配置。
        输入一批payload字典，逐个调用upsert_config做单条更新；
        upsert_config内部已经执行commit，本方法不再重复commit。
        全部更新完成后，统一批量触发一次嵌入同步后台任务。

        :param configs: 字典迭代器，每个dict包含project_id以及各个模型配置字段
        :return: 更新完成后的ORM实例列表
        """
        synced: list[ProjectAIConfig] = []
        for payload in configs:
            # 逐个处理每个项目配置，payload.get兼容字段缺失场景
            cfg = await self.upsert_config(
                project_id=payload["project_id"],
                default_chat_provider_id=payload.get("default_chat_provider_id"),
                default_chat_model=payload.get("default_chat_model"),
                default_embedding_provider_id=payload.get("default_embedding_provider_id"),
                default_embedding_model=payload.get("default_embedding_model"),
            )
            synced.append(cfg)

        # 注意：upsert_config内部已经执行commit，这里不需要再次commit

        # 批量组装所有更新项目的嵌入配置，一次性触发后台同步任务
        embed_cfgs = await build_embedding_configs(self.db, synced)
        if embed_cfgs:
            fire_and_forget_embedding_sync(embed_cfgs)
        return synced