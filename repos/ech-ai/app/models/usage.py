"""用于数据分析与监控的用量追踪数据模型。"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.project import Project


class ToolUsageRecord(BaseModel):
    """
    AI Agent 工具调用使用记录。

    记录 Agent 调用工具的时间、入参、返回结果以及性能指标，用于数据分析与监控。
    """

    __tablename__ = "ai_tool_usage_records"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="所属项目ID（逻辑引用API服务）",
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_agents.id", ondelete="CASCADE"),
        nullable=False,
        comment="调用该工具的Agent",
    )

    tool_name: Mapped[str] = mapped_column(
        String(355),
        nullable=False,
        comment='带服务商前缀的工具名（格式："工具服务商:工具名称"）',
    )

    session_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="会话/对话标识",
    )

    user_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="触发本次工具调用的用户/访问者标识",
    )

    # 工具执行详情
    input_parameters: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="传入工具的调用参数（JSON格式）",
    )

    execution_result: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="工具返回的执行结果（JSON格式）",
    )

    execution_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        comment="执行状态：pending(待执行)、success(成功)、error(错误)、timeout(超时)",
    )

    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="执行失败时的错误信息",
    )

    # 性能指标
    execution_duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="工具执行耗时，单位毫秒",
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="工具开始执行时间",
    )

    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="工具执行完成时间",
    )

    # 关联关系
    project: Mapped["Project"] = relationship(
        "Project",
        primaryjoin="foreign(ToolUsageRecord.project_id) == Project.id",
        lazy="selectin",
    )
    agent: Mapped["Agent"] = relationship("Agent", lazy="selectin")

    def __repr__(self) -> str:
        """工具调用记录的字符串表示"""
        return f"<ToolUsageRecord(id={self.id}, tool_name='{self.tool_name}', status='{self.execution_status}')>"

    @property
    def tool_provider(self) -> str:
        """从 tool_name 解析提取工具服务商"""
        if ":" in self.tool_name:
            return self.tool_name.split(":", 1)[0]
        return "unknown"

    @property
    def tool_name_only(self) -> str:
        """从 tool_name 解析提取纯工具名称（去除服务商前缀）"""
        if ":" in self.tool_name:
            return self.tool_name.split(":", 1)[1]
        return self.tool_name_only


class CollectionUsageRecord(BaseModel):
    """
    RAG知识库集合调用记录。

    记录Agent访问知识库文档集合做检索的行为，包含查询详情与性能指标，用于RAG数据分析。
    """

    __tablename__ = "ai_collection_usage_records"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="所属项目ID（逻辑引用API服务）",
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_agents.id", ondelete="CASCADE"),
        nullable=False,
        comment="访问知识库集合的Agent",
    )

    collection_id: Mapped[str] = mapped_column(
        String(36),  # UUID字符串长度
        nullable=False,
        comment="知识库集合ID（UUID字符串），引用外部RAG服务",
    )

    session_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="会话/对话标识",
    )

    user_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="触发本次检索查询的用户/访问者标识",
    )

    # 查询详情
    query_text: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="搜索查询文本或提示词",
    )

    query_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="semantic_search",
        comment="查询类型：semantic_search(语义检索)、keyword_search(关键词检索)、hybrid(混合检索)",
    )

    query_parameters: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="查询参数（过滤器、返回条数限制等）JSON格式",
    )

    # 返回结果与性能
    documents_retrieved: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="检索返回的文档切片数量",
    )

    retrieved_documents: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="检索到的文档切片，附带元数据与相似度分数",
    )

    max_relevance_score: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 4),
        nullable=True,
        comment="检索结果中最高相似度分数",
    )

    avg_relevance_score: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 4),
        nullable=True,
        comment="检索结果平均相似度分数",
    )

    # 性能指标
    query_duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="查询执行耗时，单位毫秒",
    )

    # 查询状态
    query_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        comment="查询状态：pending(待执行)、success(成功)、error(错误)、timeout(超时)",
    )

    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="查询失败时的错误信息",
    )

    # 时间戳
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="查询开始执行时间",
    )

    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="查询执行完成时间",
    )

    # 关联关系
    project: Mapped["Project"] = relationship(
        "Project",
        primaryjoin="foreign(CollectionUsageRecord.project_id) == Project.id",
        lazy="selectin",
    )
    agent: Mapped["Agent"] = relationship("Agent", lazy="selectin")

    def __repr__(self) -> str:
        """知识库集合调用记录字符串表示"""
        return f"<CollectionUsageRecord(id={self.id}, collection_id={self.collection_id}, status='{self.query_status}')>"


class AgentUsageRecord(BaseModel):
    """
    Agent用量统计记录。

    聚合统计Agent的调用量、性能、错误率，用于监控与数据分析。
    """

    __tablename__ = "ai_agent_usage_records"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="所属项目ID（逻辑引用API服务）",
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_agents.id", ondelete="CASCADE"),
        nullable=False,
        comment="被统计监控的Agent",
    )

    # 核心统计字段
    request_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Agent总请求次数",
    )

    success_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="成功请求次数",
    )

    failure_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="失败请求次数",
    )

    avg_response_time_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="平均响应耗时，单位毫秒",
    )

    last_request_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次请求发生时间",
    )

    # 时间聚合维度
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="统计周期起始时间",
    )

    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="统计周期结束时间",
    )

    aggregation_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="聚合粒度：hourly(小时)、daily(天)、weekly(周)、monthly(月)",
    )

    # 关联关系
    project: Mapped["Project"] = relationship(
        "Project",
        primaryjoin="foreign(AgentUsageRecord.project_id) == Project.id",
        lazy="selectin",
    )
    agent: Mapped["Agent"] = relationship("Agent", lazy="selectin")

    def __repr__(self) -> str:
        """Agent用量聚合记录字符串表示"""
        return f"<AgentUsageRecord(id={self.id}, agent_id={self.agent_id}, period='{self.aggregation_type}')>"