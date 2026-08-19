"""Visitor system information model."""
# 访客系统信息模型：采集访客会话的设备、浏览器、来源渠道、首次/最后访问等原始硬件与来源元数据
# 一对一依附Visitor访客；记录访客客户端环境、获客来源，用于数据分析、统计报表
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class VisitorSystemInfo(Base):
    """System metadata captured for a visitor's sessions.
    采集访客会话对应的系统/设备元数据，每个访客仅有一条记录。
    访客每次来访时更新本条记录，刷新浏览器、操作系统、最后访问时间；不新增行。
    """

    __tablename__ = "api_visitor_system_info"

    # 主键UUID，新建记录自动生成
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # 租户ID，多租户隔离
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated project ID for multi‑tenant isolation"
    )
    """
    所属租户project_id；
    ondelete="CASCADE"：数据库外键级联，租户删除，本条系统信息随之物理删除。
    """

    # 关联访客ID
    visitor_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_visitors.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated visitor ID"
    )
    """
    外键关联访客主表；
    ondelete="CASCADE"：访客被删除，数据库自动删除本条系统信息。
    """

    platform: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Acquisition or support platform name"
    )
    """获客/接入平台名称，例：web网页、h5、小程序、抖音、钉钉"""

    source_detail: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Additional context for the visitor source"
    )
    """
    来源详细信息，记录流量来源。
    例：广告投放ID、utm参数、跳转页面地址、渠道标识，用于统计分析获客效果。
    """

    browser: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Latest known browser"
    )
    """访客最近一次会话使用的浏览器，例：Chrome、Safari、微信内置浏览器"""

    operating_system: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Latest known operating system"
    )
    """访客最近一次会话操作系统，例：Windows、MacOS、Android、iOS"""

    first_seen_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="Timestamp of the first tracked session"
    )
    """该访客第一次到访系统的时间，只赋值一次，后续不再修改"""

    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="Timestamp of the last tracked session"
    )
    """该访客最近一次活跃会话时间，每次访客来访都会刷新更新"""

    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Creation timestamp"
    )
    """数据库服务端时间，记录本条记录创建时刻"""

    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="Last update timestamp"
    )
    """记录修改时，数据库自动更新为当前时间"""

    # ORM双向关系，关联Visitor访客模型
    visitor: Mapped["Visitor"] = relationship(
        "Visitor",
        back_populates="system_info",
        lazy="select"
    )
    """
    通过 system_info.visitor 获取所属访客对象。
    Visitor模型侧必须配置 system_info = relationship(back_populates="visitor", uselist=False)，构成一对一关系。
    lazy="select"：访问该属性才触发额外SQL查询。
    """

    __table_args__ = (
        # 数据库唯一约束：一个访客只能有一条系统信息，防止业务bug产生多条垃圾数据
        UniqueConstraint("visitor_id", name="uk_api_visitor_system_info_visitor"),
    )

    def __repr__(self) -> str:
        """日志、调试打印"""
        return f"<VisitorSystemInfo(visitor_id={self.visitor_id})>"