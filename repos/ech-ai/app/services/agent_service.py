"""Agent service for business logic."""
# Agent业务服务层：负责Agent的CRUD、绑定工具/知识库集合/工作流、默认Agent管理、会话内存清理、数据富化
# 职责：数据库读写、参数校验、跨服务调用(RAG/Workflow)、多对多关联维护；不直接执行Agent推理，推理交给runtime
import uuid
from typing import List, Optional, Tuple, Dict

from sqlalchemy import and_, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import NotFoundError, ValidationError
# ORM数据库模型
from app.models.agent import Agent, AgentToolAssociation
from app.models.collection import AgentCollection
from app.models.workflow import AgentWorkflow
from app.models.tool import Tool
# Pydantic入参schema
from app.schemas.agent import AgentCreate, AgentUpdate
# RPC客户端，调用其他微服务
from app.services.rag_service import rag_service_client
from app.services.workflow_service import workflow_service_client


class AgentService:
    """Service for agent‑related business logic.
    Agent业务服务，所有Agent的数据库操作入口
    依赖注入AsyncSession会话，所有DB操作复用同一个事务会话
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_agent(self, project_id: uuid.UUID, agent_data: AgentCreate) -> Agent:
        """
        Create a new agent. 创建Agent
        Args:
            project_id: 项目ID，Agent属于某个项目隔离
            agent_data: 创建入参pydantic模型

        Returns:
            Created agent 数据库Agent ORM对象

        Raises:
            ValidationError: 如果绑定的tool不存在或者不属于本项目抛出校验异常
        """
        # 如果传入工具列表，校验所有工具属于当前project
        if agent_data.tools:
            tool_ids = [tool.tool_id for tool in agent_data.tools]
            await self._validate_tools_belong_to_project(tool_ids, project_id)

        # 如果新建Agent标记为default，把本项目其他Agent全部取消默认
        if agent_data.is_default:
            await self._clear_project_default_agents(project_id)

        # 构建主Agent记录
        agent = Agent(
            project_id=project_id,
            llm_provider_id=agent_data.llm_provider_id,
            name=agent_data.name,
            instruction=agent_data.instruction,
            model=agent_data.model,
            is_default=agent_data.is_default,
            is_remote_store_agent=agent_data.is_remote_store_agent,
            remote_agent_url=agent_data.remote_agent_url,
            store_agent_id=agent_data.store_agent_id,
            config=agent_data.config,
            bound_device_id=agent_data.bound_device_id,
        )

        self.db.add(agent)
        await self.db.flush()  # flush，不commit，拿到数据库生成的agent.id，用于建立关联表

        # 多对多：Agent‑Tool绑定关系，存入中间表 AgentToolAssociation
        if agent_data.tools:
            for tool_binding in agent_data.tools:
                association = AgentToolAssociation(
                    agent_id=agent.id,
                    tool_id=tool_binding.tool_id,
                    enabled=tool_binding.enabled,      # 该Agent下此工具是否启用
                    permissions=tool_binding.permissions, # 工具权限
                    config=tool_binding.config,        # 工具在此Agent实例下的私有配置
                )
                self.db.add(association)

        # 多对多：Agent绑定RAG知识库集合 AgentCollection
        if agent_data.collections:
            for collection_id_str in agent_data.collections:
                agent_collection = AgentCollection(
                    agent_id=agent.id,
                    collection_id=collection_id_str,
                )
                self.db.add(agent_collection)

        # 多对多：Agent绑定子工作流 AgentWorkflow
        if agent_data.workflows:
            for workflow_id_str in agent_data.workflows:
                agent_workflow = AgentWorkflow(
                    agent_id=agent.id,
                    workflow_id=workflow_id_str,
                )
                self.db.add(agent_workflow)

        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def get_agent(self, project_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        """
        Get an agent by ID. 查询单个Agent详情，带关联数据 + 外部服务富化
        Args:
            project_id: 项目ID
            agent_id: Agent主键ID

        Returns:
            Agent ORM对象，附加 _collection_data / _workflow_data / _tools_data 富化字段

        Raises:
            NotFoundError: Agent不存在或者已经软删除
        """
        stmt = (
            select(Agent)
            # 预加载多对多关联，避免N+1查询
            .options(
                selectinload(Agent.tools),
                selectinload(Agent.collections),
                selectinload(Agent.workflows),
                selectinload(Agent.llm_provider),
            )
            .where(
                and_(
                    Agent.id == agent_id,
                    Agent.project_id == project_id,
                    Agent.deleted_at.is_(None), # 过滤软删除
                )
            )
        )
        result = await self.db.execute(stmt)
        agent = result.scalar_one_or_none()

        if not agent:
            raise NotFoundError("Agent", agent_id)

        # 三层富化：调用外部服务补齐知识库、工作流、工具详情；挂载临时属性 _xxx_data，用于序列化返回前端
        enriched_agents = await self.enrich_agents_with_collection_data([agent], project_id)
        enriched_agents = await self.enrich_agents_with_workflow_data(enriched_agents, project_id)
        enriched_agents = await self.enrich_agents_with_tool_details(enriched_agents, project_id)
        return enriched_agents[0]

    async def list_agents(
        self,
        project_id: uuid.UUID,
        model: Optional[str] = None,
        is_default: Optional[bool] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Agent], int]:
        """
        List agents for a project. 分页查询项目下Agent列表，支持过滤model、is_default
        Returns:
            Tuple of (agents, total_count) 结果列表 + 总条数，用于分页
        """
        conditions = [
            Agent.project_id == project_id,
            Agent.deleted_at.is_(None),
        ]

        # 动态拼接过滤条件
        if model is not None:
            conditions.append(Agent.model == model)
        if is_default is not None:
            conditions.append(Agent.is_default == is_default)

        # count统计总记录
        count_stmt = select(func.count(Agent.id)).where(and_(*conditions))
        count_result = await self.db.execute(count_stmt)
        total_count = count_result.scalar()

        # 分页查询，预加载关联
        stmt = (
            select(Agent)
            .options(
                selectinload(Agent.tools),
                selectinload(Agent.collections),
                selectinload(Agent.workflows),
                selectinload(Agent.llm_provider),
            )
            .where(and_(*conditions))
            .order_by(Agent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        agents = result.scalars().all()

        # 批量富化列表内所有Agent
        enriched_agents = await self.enrich_agents_with_collection_data(list(agents), project_id)
        enriched_agents = await self.enrich_agents_with_workflow_data(enriched_agents, project_id)
        enriched_agents = await self.enrich_agents_with_tool_details(enriched_agents, project_id)

        return enriched_agents, total_count

    async def update_agent(
        self, project_id: uuid.UUID, agent_id: uuid.UUID, agent_data: AgentUpdate
    ) -> Agent:
        """
        Update an agent. 更新Agent，支持更新基础字段、工具、知识库、工作流绑定
        > 注意：更新绑定关系是全量覆盖：传入tools列表代表新的全部绑定，旧关联全部删除重建
        Args:
            project_id: 项目ID
            agent_id: Agent ID
            agent_data: 更新入参

        Returns:
            Updated agent

        Raises:
            NotFoundError: Agent不存在
        """
        agent = await self.get_agent(project_id, agent_id)

        # 校验传入的collection/workflow/tool都属于本项目
        if agent_data.collections is not None:
            await self._validate_collections_belong_to_project(agent_data.collections, project_id)
        if agent_data.workflows is not None:
            await self._validate_workflows_belong_to_project(agent_data.workflows, project_id)
        if agent_data.tools is not None:
            tool_ids = [tool.tool_id for tool in agent_data.tools]
            await self._validate_tools_belong_to_project(tool_ids, project_id)

        # 更新基础字段，exclude_unset只更新传入的字段，排除多对多关联字段
        update_data = agent_data.model_dump(exclude_unset=True, exclude={"tools", "collections", "workflows"})
        for field, value in update_data.items():
            setattr(agent, field, value)

        # 如果本次更新设为default，清除项目其他Agent的default标记
        if agent_data.is_default is True:
            await self._clear_project_default_agents(
                project_id,
                exclude_agent_id=agent.id,
            )

        # ✅ 更新工具绑定：全量删除旧关联，插入新关联（覆盖模式）
        if agent_data.tools is not None:
            stmt_delete = select(AgentToolAssociation).where(
                and_(
                    AgentToolAssociation.agent_id == agent.id,
                    AgentToolAssociation.deleted_at.is_(None),
                )
            )
            result = await self.db.execute(stmt_delete)
            existing_associations = result.scalars().all()
            for association in existing_associations:
                await self.db.delete(association)

            for tool_binding in agent_data.tools:
                association = AgentToolAssociation(
                    agent_id=agent.id,
                    tool_id=tool_binding.tool_id,
                    enabled=tool_binding.enabled,
                    permissions=tool_binding.permissions,
                    config=tool_binding.config,
                )
                self.db.add(association)
            await self.db.flush()

        # ✅ 更新知识库集合绑定：删除旧，新增新（全量覆盖）
        if agent_data.collections is not None:
            for agent_collection in agent.collections:
                await self.db.delete(agent_collection)
            for collection_id_str in agent_data.collections:
                agent_collection = AgentCollection(
                    agent_id=agent.id,
                    collection_id=collection_id_str,
                )
                self.db.add(agent_collection)

        # ✅ 更新工作流绑定：全量覆盖
        if agent_data.workflows is not None:
            for agent_workflow in agent.workflows:
                await self.db.delete(agent_workflow)
            for workflow_id_str in agent_data.workflows:
                agent_workflow = AgentWorkflow(
                    agent_id=agent.id,
                    workflow_id=workflow_id_str,
                )
                self.db.add(agent_workflow)

        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def get_default_agent(self, project_id: uuid.UUID) -> Agent:
        """Get the current default agent for a project. 获取项目默认Agent"""
        agents, _ = await self.list_agents(
            project_id=project_id,
            is_default=True,
            limit=1,
            offset=0,
        )
        if not agents:
            raise NotFoundError(
                "Default agent",
                details={"project_id": str(project_id)},
            )
        return agents[0]

    async def delete_agent(self, project_id: uuid.UUID, agent_id: uuid.UUID) -> None:
        """
        Soft delete an agent. Agent软删除，不会物理删除记录，设置deleted_at
        """
        agent = await self.get_agent(project_id, agent_id)
        agent.soft_delete()
        await self.db.commit()

    async def set_tool_enabled(
        self, project_id: uuid.UUID, agent_id: uuid.UUID, tool_id: uuid.UUID, enabled: bool
    ) -> None:
        """Enable or disable a specific tool binding for an agent.
        局部开关：不覆盖全部绑定，只修改某一个工具在该Agent下的启用状态
        """
        stmt_agent = select(Agent).where(
            and_(Agent.id == agent_id, Agent.project_id == project_id, Agent.deleted_at.is_(None))
        )
        res = await self.db.execute(stmt_agent)
        agent = res.scalar_one_or_none()
        if not agent:
            raise NotFoundError("Agent", agent_id)

        stmt_tool = select(AgentToolAssociation).where(
            and_(
                AgentToolAssociation.agent_id == agent_id,
                AgentToolAssociation.tool_id == tool_id,
                AgentToolAssociation.deleted_at.is_(None),
            )
        )
        res_tool = await self.db.execute(stmt_tool)
        binding = res_tool.scalar_one_or_none()
        if not binding:
            raise NotFoundError("AgentToolAssociation", details={"tool_id": str(tool_id)})

        binding.enabled = enabled
        await self.db.commit()

    async def set_collection_enabled(
        self, project_id: uuid.UUID, agent_id: uuid.UUID, collection_id: str, enabled: bool
    ) -> None:
        """Enable or disable a specific collection binding for an agent. 单独开关某个知识库集合"""
        stmt_agent = select(Agent).where(
            and_(Agent.id == agent_id, Agent.project_id == project_id, Agent.deleted_at.is_(None))
        )
        res = await self.db.execute(stmt_agent)
        agent = res.scalar_one_or_none()
        if not agent:
            raise NotFoundError("Agent", agent_id)

        stmt_col = select(AgentCollection).where(
            and_(
                AgentCollection.agent_id == agent_id,
                AgentCollection.collection_id == collection_id,
                AgentCollection.deleted_at.is_(None),
            )
        )
        res_col = await self.db.execute(stmt_col)
        binding = res_col.scalar_one_or_none()
        if not binding:
            raise NotFoundError("AgentCollection", details={"collection_id": collection_id})

        binding.enabled = enabled
        await self.db.commit()

    async def set_workflow_enabled(
        self, project_id: uuid.UUID, agent_id: uuid.UUID, workflow_id: str, enabled: bool
    ) -> None:
        """Enable or disable a specific workflow binding for an agent. 单独开关某个绑定的子工作流"""
        stmt_agent = select(Agent).where(
            and_(Agent.id == agent_id, Agent.project_id == project_id, Agent.deleted_at.is_(None))
        )
        res = await self.db.execute(stmt_agent)
        agent = res.scalar_one_or_none()
        if not agent:
            raise NotFoundError("Agent", agent_id)

        stmt_wf = select(AgentWorkflow).where(
            and_(
                AgentWorkflow.agent_id == agent_id,
                AgentWorkflow.workflow_id == workflow_id,
            )
        )
        res_wf = await self.db.execute(stmt_wf)
        binding = res_wf.scalar_one_or_none()
        if not binding:
            raise NotFoundError("AgentWorkflow", details={"workflow_id": workflow_id})

        binding.enabled = enabled
        await self.db.commit()

    async def clear_session_memory(
        self, session_id: str, project_id: uuid.UUID, user_id: Optional[str] = None
    ) -> None:
        """Clear all memory and session history for a specific session.
        清空Agno会话记忆与历史，直接执行原生SQL操作ai schema下agno_memories、agno_sessions
        捕获异常：表还未由Agno自动创建时执行SQL会报错，静默跳过；出错回滚事务
        """
        try:
            # 用户个人记忆
            if user_id:
                try:
                    await self.db.execute(
                        text("DELETE FROM ai.agno_memories WHERE user_id = :user_id"),
                        {"user_id": user_id}
                    )
                except Exception:
                    pass
            # 会话对话历史
            try:
                await self.db.execute(
                    text("DELETE FROM ai.agno_sessions WHERE session_id = :session_id"),
                    {"session_id": session_id}
                )
            except Exception:
                pass

            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    async def _replace_project_default_agent(
        self,
        project_id: uuid.UUID,
        new_default_agent_id: uuid.UUID,
    ) -> None:
        """Clear any other default agent before setting the requested default."""
        await self._clear_project_default_agents(
            project_id,
            exclude_agent_id=new_default_agent_id,
        )

    async def _clear_project_default_agents(
        self,
        project_id: uuid.UUID,
        exclude_agent_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Clear active default agents in a project before promoting another one.
        内部工具方法：把项目内其他Agent的is_default置False；exclude_agent_id用于保留当前要设为默认的Agent
        """
        conditions = [
            Agent.project_id == project_id,
            Agent.deleted_at.is_(None),
            Agent.is_default.is_(True),
        ]
        if exclude_agent_id is not None:
            conditions.append(Agent.id != exclude_agent_id)

        await self.db.execute(
            update(Agent)
            .where(and_(*conditions))
            .values(is_default=False)
        )

    async def _validate_collections_belong_to_project(
        self, collection_ids: List[str], project_id: uuid.UUID
    ) -> None:
        """校验collection列表在RAG服务真实存在，属于本项目（RPC调用rag_service_client）"""
        if not collection_ids:
            return
        await rag_service_client.validate_collections_exist(
            collection_ids,
            str(project_id),
        )

    async def _validate_workflows_belong_to_project(
        self, workflow_ids: List[str], project_id: uuid.UUID
    ) -> None:
        """校验workflow列表在Workflow服务真实存在，属于本项目（RPC调用workflow_service_client）"""
        if not workflow_ids:
            return
        await workflow_service_client.validate_workflows_exist(
            workflow_ids,
            str(project_id),
        )

    async def _validate_tools_belong_to_project(
        self, tool_ids: List[uuid.UUID], project_id: uuid.UUID
    ) -> None:
        """校验工具ID列表：数据库存在，并且属于当前project，防止越权绑定其他项目工具"""
        if not tool_ids:
            return

        stmt = select(Tool).where(
            and_(
                Tool.id.in_(tool_ids),
                Tool.deleted_at.is_(None),
            )
        )
        result = await self.db.execute(stmt)
        tools = result.scalars().all()

        found_tool_ids = {tool.id for tool in tools}
        missing_tool_ids = set(tool_ids) - found_tool_ids
        if missing_tool_ids:
            raise NotFoundError(
                "Tool",
                details={"missing_tool_ids": [str(tid) for tid in missing_tool_ids]},
            )

        wrong_project_tools = [tool for tool in tools if tool.project_id != project_id]
        if wrong_project_tools:
            raise ValidationError(
                "Some tools belong to a different project",
                "tool_ids",
                {
                    "wrong_project_tool_ids": [str(tool.id) for tool in wrong_project_tools],
                    "expected_project_id": str(project_id),
                },
            )

    async def enrich_agents_with_collection_data(
        self, agents: List[Agent], project_id: uuid.UUID
    ) -> List[Agent]:
        """
        Agent数据富化：批量从RAG服务拉取知识库详情，挂载临时属性 agent._collection_data
        业务：ORM只存collection_id；真实名称、描述、向量库信息在RAG微服务；失败则返回空列表，不阻断主流程
        """
        if not agents:
            return agents

        all_collection_ids = set()
        for agent in agents:
            for ac in (agent.collections or []):
                all_collection_ids.add(ac.collection_id)

        if not all_collection_ids:
            for agent in agents:
                agent._collection_data = []
            return agents

        try:
            batch_response = await rag_service_client.get_collections_batch(
                list(all_collection_ids),
                str(project_id),
            )
            collection_data_map = {
                str(collection.id): collection
                for collection in batch_response.collections
            }

            for agent in agents:
                agent_collection_data = []
                for ac in (agent.collections or []):
                    cid = str(ac.collection_id)
                    if cid in collection_data_map:
                        col = collection_data_map[cid]
                        try:
                            col_with_enabled = col.model_copy(update={"enabled": bool(getattr(ac, "enabled", True))})
                        except Exception:
                            col_with_enabled = col
                        agent_collection_data.append(col_with_enabled)
                agent._collection_data = agent_collection_data

        except Exception:
            # RAG服务异常降级，不抛异常，富化字段为空
            for agent in agents:
                agent._collection_data = []

        return agents

    async def enrich_agents_with_workflow_data(
        self, agents: List[Agent], project_id: uuid.UUID
    ) -> List[Agent]:
        """Agent数据富化：批量从Workflow服务拉取子工作流详情，挂载 agent._workflow_data"""
        if not agents:
            return agents

        all_workflow_ids = set()
        for agent in agents:
            for aw in (agent.workflows or []):
                all_workflow_ids.add(aw.workflow_id)

        if not all_workflow_ids:
            for agent in agents:
                agent._workflow_data = []
            return agents

        try:
            workflows = await workflow_service_client.get_workflows_batch(
                list(all_workflow_ids),
                str(project_id),
            )
            workflow_data_map = {
                str(workflow.id): workflow
                for workflow in workflows
            }

            for agent in agents:
                agent_workflow_data = []
                for aw in (agent.workflows or []):
                    wid = str(aw.workflow_id)
                    if wid in workflow_data_map:
                        wf = workflow_data_map[wid]
                        try:
                            wf_with_enabled = wf.model_copy(update={"enabled": bool(getattr(aw, "enabled", True))})
                        except Exception:
                            wf_with_enabled = wf
                        agent_workflow_data.append(wf_with_enabled)
                agent._workflow_data = agent_workflow_data

        except Exception:
            for agent in agents:
                agent._workflow_data = []

        return agents

    async def enrich_agents_with_tool_details(
        self, agents: List[Agent], project_id: uuid.UUID
    ) -> List[Agent]:
        """
        Agent数据富化：读取本地数据库Tool表，结合中间表绑定信息，组装AgentToolDetail，挂载 agent._tools_data
        关键点：Tool是全局实体；AgentToolAssociation保存该Agent视角下：enabled、permissions、tool_config；
        把两部分合并组装返回给前端的完整工具详情。
        """
        if not agents:
            return agents

        # 批量查询所有传入Agent的工具绑定中间表
        assoc_stmt = (
            select(
                AgentToolAssociation.agent_id,
                AgentToolAssociation.tool_id,
                AgentToolAssociation.enabled,
                AgentToolAssociation.permissions,
                AgentToolAssociation.config,
            )
            .where(
                and_(
                    AgentToolAssociation.agent_id.in_([a.id for a in agents]),
                    AgentToolAssociation.deleted_at.is_(None),
                )
            )
        )
        assoc_res = await self.db.execute(assoc_stmt)
        assoc_map: Dict[Tuple[uuid.UUID, uuid.UUID], Tuple[bool, Optional[List[str]], Optional[dict]]] = {
            (row[0], row[1]): (bool(row[2]), row[3], row[4]) for row in assoc_res.all()
        }

        # 局部导入，解决循环导入
        from app.schemas.tool import AgentToolDetail

        for agent in agents:
            tool_details = []
            for tool_entity in (agent.tools or []):
                if not tool_entity:
                    continue
                # 获取该Agent‑Tool绑定的个性化配置
                assoc_data = assoc_map.get((agent.id, tool_entity.id), (True, None, None))
                enabled, permissions, tool_config = assoc_data

                try:
                    tool_dict = {
                        "id": tool_entity.id,
                        "project_id": tool_entity.project_id,
                        "name": tool_entity.name,
                        "description": tool_entity.description,
                        "tool_type": tool_entity.tool_type,
                        "transport_type": tool_entity.transport_type,
                        "endpoint": tool_entity.endpoint,
                        "config": tool_entity.config,
                        "created_at": tool_entity.created_at,
                        "updated_at": tool_entity.updated_at,
                        "deleted_at": tool_entity.deleted_at,
                        "enabled": enabled,
                        "permissions": permissions,
                        "tool_config": tool_config,
                    }
                    tool_detail = AgentToolDetail(**tool_dict)
                    tool_details.append(tool_detail)
                except Exception:
                    continue

            agent._tools_data = tool_details

        return agents