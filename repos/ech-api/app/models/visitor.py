"""Visitor model."""

from datetime import datetime
from enum import Enum
from typing import List, Optional, TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, foreign
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.models.platform import Platform
from app.models.project import Project
from app.models.visitor_ai_insight import VisitorAIInsight
from app.models.visitor_ai_profile import VisitorAIProfile
from app.models.visitor_system_info import VisitorSystemInfo

if TYPE_CHECKING:
    from app.models.visitor_activity import VisitorActivity
    from app.models.visitor_tag import VisitorTag
    from app.models.tag import Tag
    from app.models.visitor_customer_update import VisitorCustomerUpdate
    from app.models.visitor_session import VisitorSession

class VisitorServiceStatus(str, Enum):
    """Visitor service status enumeration.

    State transitions:
    - NEW: Initial state when visitor is created
    - QUEUED: Visitor is in the waiting queue
    - ACTIVE: Staff is actively serving the visitor
    - CLOSED: Service session is closed

    Allowed transitions:
    - NEW -> QUEUED (visitor requests human service)
    - NEW -> ACTIVE (direct assignment without queue)
    - QUEUED -> ACTIVE (staff assigned from queue)
    - ACTIVE -> CLOSED (service ends)
    - CLOSED -> QUEUED (visitor requests service again)
    - CLOSED -> ACTIVE (visitor re‑engaged)
    """

    NEW = "new"             # Visitor just created, no service requested
    QUEUED = "queued"       # In waiting queue for human service
    ACTIVE = "active"       # Currently being served by staff
    CLOSED = "closed"       # Service session closed


# Statuses indicating visitor is unassigned (can be assigned to staff)
UNASSIGNED_STATUSES = {VisitorServiceStatus.NEW.value, VisitorServiceStatus.CLOSED.value}


class Visitor(Base):
    """Visitor model for external users/customers.
    访客主模型，外部客户/用户核心数据表；
    一个Visitor代表一位独立访客，所有AI洞察、画像、系统信息、行为流水、标签都通过外键/relationship依附本表。
    支持软删除；内置状态机控制人工客服服务流转。
    """

    __tablename__ = "api_visitors"

    # ========== 主键 ==========
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    """访客唯一UUID主键"""

    # ========== 外键 ==========
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated project ID for multi‑tenant isolation"
    )
    """所属租户ID；租户删除，数据库级联删除全部访客数据"""

    platform_id: Mapped[UUID] = mapped_column(
        nullable=False,
        comment="Associated platform ID"
    )
    """接入渠道平台ID，关联Platform渠道表；没有设置数据库外键约束，由业务代码保证完整性"""

    # ========== 基础访客资料字段 ==========
    platform_open_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Visitor unique identifier on this platform"
    )
    """第三方渠道给到访客唯一标识，例如微信openid；同一个platform下open_id唯一识别访客"""

    name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Visitor real name"
    )
    """访客真实姓名"""

    nickname: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Visitor nickname on this platform (English)"
    )
    """平台昵称（英文）"""

    nickname_zh: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Visitor nickname in Chinese"
    )
    """平台中文昵称"""

    avatar_url: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Visitor avatar URL on this platform"
    )
    """访客头像链接"""

    phone_number: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
        comment="Visitor phone number on this platform"
    )
    """手机号"""

    email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Visitor email on this platform"
    )
    """邮箱"""

    company: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Visitor company or organization"
    )
    """公司/组织"""

    job_title: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Visitor job title or position"
    )
    """职位"""

    source: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Acquisition source describing how the visitor found us"
    )
    """获客来源，记录访客从哪里进入系统"""

    note: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Additional notes about the visitor"
    )
    """客服人员手动备注，大文本"""

    custom_attributes: Mapped[dict[str, str | None]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Arbitrary custom attributes set by staff"
    )
    """客服自定义扩展字段，JSONB字典，存放业务自定义K‑V，无需DDL改表"""

    # ========== 会话活跃度追踪字段 ==========
    first_visit_time: Mapped[datetime] = mapped_column(
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
        comment="When the visitor first accessed the system"
    )
    """首次访问时间；server_default数据库默认值，default ORM内存默认，双重兜底"""

    last_visit_time: Mapped[datetime] = mapped_column(
        nullable=False,
        default=datetime.utcnow,
        server_default=func.now(),
        comment="Visitor most recent activity/visit time"
    )
    """最近一次访问/活跃时间"""

    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="Time of the last message in the channel"
    )
    """通道内最后一条消息发生时间"""

    visitor_send_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        comment="Total number of messages sent by the visitor"
    )
    """访客累计发送消息总数"""

    last_message_seq: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        comment="Sequence number of the last message in the channel"
    )
    """通道内消息序列号，用于消息顺序控制"""

    last_client_msg_no: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Client message number of the last message in the channel"
    )
    """第三方客户端消息编号"""

    is_last_message_from_visitor: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether the last message in the channel was sent by the visitor"
    )
    """最后一条消息是否来自访客"""

    is_last_message_from_ai: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether the last message in the channel was sent by an AI"
    )
    """最后一条消息是否来自AI机器人"""

    last_offline_time: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="Most recent time visitor went offline (NULL when never offline or currently online)"
    )
    """最近离线时间；在线状态时值为NULL"""

    is_online: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether the visitor is currently online/active"
    )
    """访客当前是否在线"""

    ai_disabled: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        default=None,
        comment="Whether AI responses are disabled for this visitor"
    )
    """是否对该访客关闭AI自动回复；None代表继承租户/平台全局配置"""

    ai_fallback_retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Number of failed AI fallback attempts"
    )
    """AI降级失败重试计数，用于熔断控制"""

    # ========== 时区、语言、IP与IP解析地理信息 ==========
    timezone: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Visitor timezone (e.g., 'Asia/Shanghai', 'America/New_York')"
    )
    """访客时区 IANA格式"""

    language: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
        comment="Visitor preferred language code (e.g., 'en', 'zh‑CN')"
    )
    """访客偏好语言码"""

    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
        comment="Visitor IP address (supports both IPv4 and IPv6)"
    )
    """访客IP地址，45位兼容IPv6"""

    geo_country: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Country name derived from IP address"
    )
    """IP解析得到国家名称"""

    geo_country_code: Mapped[Optional[str]] = mapped_column(
        String(2),
        nullable=True,
        comment="ISO 3166‑1 alpha‑2 country code (e.g., 'US', 'CN')"
    )
    """两位国家ISO编码"""

    geo_region: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Region/state/province name"
    )
    """省/州"""

    geo_city: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="City name"
    )
    """城市"""

    geo_isp: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Internet Service Provider (available with ip2region)"
    )
    """运营商信息，依赖IP库解析"""

    # ========== 客服服务状态机 ==========
    service_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=VisitorServiceStatus.NEW.value,
        comment="Service status: new, queued, active, closed"
    )
    """
    访客服务状态，对应枚举VisitorServiceStatus：
    new新建 / queued排队中 / active坐席接待中 / closed会话已关闭
    """

    # ========== 时间戳 & 软删除 ==========
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Creation timestamp"
    )
    """记录创建时间"""

    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="Last update timestamp"
    )
    """记录更新时间"""

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="Soft deletion timestamp"
    )
    """软删除时间；不为NULL代表访客被逻辑删除"""

    # ========== ORM关系映射（全部配置 cascade="all, delete‑orphan" ==========
    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="visitors",
        lazy="select"
    )
    """反向关联租户Project"""

    platform: Mapped["Platform"] = relationship(
        "Platform",
        primaryjoin="foreign(Visitor.platform_id) == Platform.id",
        foreign_keys="Visitor.platform_id",
        back_populates="visitors",
        lazy="select"
    )
    """关联接入渠道Platform；显式指定primaryjoin条件，因为platform_id没有数据库ForeignKey约束"""

    visitor_tags: Mapped[List["VisitorTag"]] = relationship(
        "VisitorTag",
        back_populates="visitor",
        cascade="all, delete‑orphan",
        lazy="select"
    )
    """访客‑标签中间表集合；delete‑orphan：Visitor删除，全部VisitorTag自动删除"""

    ai_profile: Mapped[Optional["VisitorAIProfile"]] = relationship(
        "VisitorAIProfile",
        back_populates="visitor",
        cascade="all, delete‑orphan",
        lazy="select",
        uselist=False
    )
    """一对一：访客长期AI画像，uselist=False返回单个对象"""

    ai_insight: Mapped[Optional["VisitorAIInsight"]] = relationship(
        "VisitorAIInsight",
        back_populates="visitor",
        cascade="all, delete‑orphan",
        lazy="select",
        uselist=False
    )
    """一对一：访客单轮会话AI即时洞察"""

    system_info: Mapped[Optional["VisitorSystemInfo"]] = relationship(
        "VisitorSystemInfo",
        back_populates="visitor",
        cascade="all, delete‑orphan",
        lazy="select",
        uselist=False
    )
    """一对一：访客设备、来源系统信息"""

    activities: Mapped[List["VisitorActivity"]] = relationship(
        "VisitorActivity",
        back_populates="visitor",
        cascade="all, delete‑orphan",
        lazy="select"
    )
    """一对多：访客行为流水时间轴记录"""

    customer_updates: Mapped[List["VisitorCustomerUpdate"]] = relationship(
        "VisitorCustomerUpdate",
        back_populates="visitor",
        cascade="all, delete‑orphan",
        lazy="select",
    )
    """一对多：客户资料变更历史记录"""

    sessions: Mapped[List["VisitorSession"]] = relationship(
        "VisitorSession",
        back_populates="visitor",
        cascade="all, delete‑orphan",
        lazy="select",
    )
    """一对多：访客会话列表，一次对话对应一条session"""

    def __repr__(self) -> str:
        """String representation of the visitor."""
        display_name = self.name or self.nickname or self.platform_open_id
        return f"<Visitor(id={self.id}, name='{display_name}')>"

    @property
    def is_deleted(self) -> bool:
        """Check if the visitor is soft deleted.
        判断访客是否软删除
        """
        return self.deleted_at is not None

    @property
    def platform_type(self) -> Optional[str]:
        """Convenience accessor for the associated platform type.
        Returns the platform.type string (e.g., 'website', 'wechat') when available.
        快捷属性，获取所属渠道类型，避免业务频繁写visitor.platform.type；做异常捕获防止未预加载时报错
        """
        try:
            return self.platform.type if self.platform is not None else None
        except Exception:
            return None

    @property
    def display_name(self) -> str:
        """Get the best available display name for the visitor.
        获取前端展示用名称优先级：真实姓名 > 昵称 > 渠道open_id
        """
        return self.name or self.nickname or self.platform_open_id

    @property
    def is_unassigned(self) -> bool:
        """Check if visitor is unassigned (can be assigned to staff).
        判断访客是否处于可分配坐席状态，基于UNASSIGNED_STATUSES集合
        """
        return self.service_status in UNASSIGNED_STATUSES

    @property
    def tags(self) -> List["Tag"]:
        """Get active tags for the visitor.
        快捷属性：过滤得到访客**有效未删除标签**
        过滤条件：中间表VisitorTag未软删除，Tag主记录本身也未软删除
        """
        return [
            vt.tag
            for vt in self.visitor_tags
            if vt.tag and vt.deleted_at is None and vt.tag.deleted_at is None
        ]

    def set_status_queued(self) -> None:
        """Set visitor status to QUEUED.
        实例方法：状态流转 → 设置排队；更新updated_at时间戳
        """
        self.service_status = VisitorServiceStatus.QUEUED.value
        self.updated_at = datetime.utcnow()

    def set_status_active(self) -> None:
        """Set visitor status to ACTIVE.
        实例方法：状态流转 → 设置坐席接待中
        """
        self.service_status = VisitorServiceStatus.ACTIVE.value
        self.updated_at = datetime.utcnow()

    def set_status_closed(self) -> None:
        """Set visitor status to CLOSED.
        实例方法：状态流转 → 关闭本次人工服务
        """
        self.service_status = VisitorServiceStatus.CLOSED.value
        self.updated_at = datetime.utcnow()