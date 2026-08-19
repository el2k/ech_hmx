"""Platform model."""
# 渠道模型：管理各个沟通渠道（网站、微信、企业微信、钉钉机器人、飞书机器人、WhatsApp等）ORM定义

from datetime import datetime
from enum import Enum
from typing import List, Optional, TYPE_CHECKING
from uuid import UUID, uuid4

# TYPE_CHECKING 仅类型检查阶段生效，运行时不会导入，解决模型之间循环导入问题
if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.visitor import Visitor

# SQLAlchemy导入：字段类型、外键、PostgreSQL特有JSONB/UUID、ORM映射、关系、事件钩子、inspect检查实体变更
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, func, event, inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, foreign

# 数据库基类，所有表继承 Base
from app.core.database import Base


class PlatformType(str, Enum):
    """Platform type enumeration.
    渠道类型枚举：代码层面常量定义；真正展示/可配置元数据存储在 PlatformTypeDefinition 数据表
    """
    WEBSITE = "website"
    WECHAT = "wechat"
    WECHAT_PERSONAL = "wechat_personal"  # 个人微信
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    EMAIL = "email"
    SMS = "sms"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    DISCORD = "discord"
    SLACK = "slack"
    TEAMS = "teams"
    PHONE = "phone"
    DOUYIN = "douyin"
    TIKTOK = "tiktok"
    CUSTOM = "custom"
    WECOM = "wecom"  # 企业微信
    WECOM_BOT = "wecom_bot"  # 企业微信机器人
    FEISHU_BOT = "feishu_bot"  # 飞书机器人
    DINGTALK_BOT = "dingtalk_bot"  # 钉钉机器人


class PlatformTypeDefinition(Base):
    """Database-backed metadata for supported platform types.
    渠道类型元数据表 api_platform_types
    作用：把渠道的展示信息放到数据库，不用改代码发版本就可以：新增渠道、修改图标、开关是否支持
    存储：type(和Platform.type关联)、显示名、英文名称、是否启用、SVG图标
    """
    __tablename__ = "api_platform_types"

    # 主键，UUID自动生成
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Basic fields
    type: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        comment="Stable identifier (e.g., wechat, website, email)"
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Human-readable platform name"
    )
    name_en: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="English name of the platform type (e.g., 'WeCom', 'Website')",
    )
    is_supported: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this platform type is currently supported",
    )
    icon: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="SVG icon markup for display"
    )

    # Timestamps 数据库服务端时间
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Creation timestamp"
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="Last update timestamp"
    )

    # Relationships
    # viewonly=True：只读关系，只做查询用，不会通过这个关系做新增修改；primaryjoin手动指定关联条件
    # Platform.type 外键逻辑关联本表type字段，不是传统外键约束，只是ORM层面join
    platforms: Mapped[List["Platform"]] = relationship(
        "Platform",
        primaryjoin="PlatformTypeDefinition.type == foreign(Platform.type)",
        viewonly=True,
        lazy="select"
    )

    def __repr__(self) -> str:
        """String representation of the platform type. 调试打印对象"""
        return f"<PlatformTypeDefinition(id={self.id}, type='{self.type}')>"


class PlatformSyncStatus(str, Enum):
    """渠道跨服务同步状态枚举。Platform实体变更后同步到Platform Service平台服务"""
    PENDING = "pending"   # 待同步
    SYNCED = "synced"     # 同步成功
    FAILED = "failed"     # 同步失败


class PlatformAIMode(str, Enum):
    """Platform AI mode enumeration.
    渠道AI处理模式
    """
    AUTO = "auto"         # 自动：AI 自动处理所有消息
    ASSIST = "assist"     # 辅助：人工优先，超时后 AI 接管
    OFF = "off"           # 关闭：AI 不处理消息


class Platform(Base):
    """Platform model for communication platforms.
    api_platforms表：属于某个Project的实际渠道实例
    多租户隔离：project_id外键；支持软删除；对接凭证config(JSONB)；AI模式配置；跨服务同步字段
    """
    __tablename__ = "api_platforms"

    # Primary key UUID主键
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Foreign keys
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated project ID for multi‑tenant isolation"
    )

    # Basic fields
    name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Platform name (e.g., WeChat, WhatsApp)"
    )
    type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Platform type from predefined enum"
    )
    api_key: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Platform‑specific API key for integrations"
    )
    config: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Platform‑specific configuration，渠道自定义配置存JSONB，密钥、token、回调地址等"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether platform is active"
    )

    # AI configuration 当前渠道绑定的AI Agent、AI工作模式、人工转AI超时秒数
    agent_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        comment="AI Agent ID assigned to this platform"
    )
    ai_mode: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        default=PlatformAIMode.AUTO.value,
        comment="AI mode: auto (AI handles all), assist (human first, AI fallback), off (AI disabled)"
    )
    fallback_to_ai_timeout: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        default=0,
        comment="Timeout in seconds before AI takes over when ai_mode=assist. 0 means AI never takes over."
    )

    # Website usage tracking 网站渠道专属字段：记录访客第一次访问的站点URL与页面标题
    is_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether the platform (specifically website type) has been used"
    )
    used_website_url: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True,
        comment="The URL of the website where this platform was first used"
    )
    used_website_title: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="The title of the website where this platform was first used"
    )

    # Logo storage 渠道logo文件相对路径
    logo_path: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="Relative path to logo file under PLATFORM_LOGO_UPLOAD_DIR",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Creation timestamp"
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="Last update timestamp"
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="Soft deletion timestamp，软删除：不为NULL代表已删除，不执行数据库DELETE"
    )

    # Sync tracking fields 【重点】跨服务同步状态字段，对应前面聊的平台数据同步
    sync_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PlatformSyncStatus.PENDING.value,
        comment="Synchronization status with Platform Service (pending|synced|failed)",
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="Timestamp of last successful sync",
    )
    sync_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Last synchronization error message，保存最近一次同步失败报错信息",
    )
    sync_retry_count: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        comment="Number of sync retry attempts，同步失败重试计数，用于退避策略",
    )

    # Relationships
    # 所属项目，双向关系 Project.platforms
    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="platforms",
        lazy="select"
    )

    # 该渠道下全部访客会话 Visitor
    visitors: Mapped[List["Visitor"]] = relationship(
        "Visitor",
        primaryjoin="Platform.id == foreign(Visitor.platform_id)",
        foreign_keys="Visitor.platform_id",
        back_populates="platform",
        lazy="select"
    )

    # 关联渠道类型元数据，viewonly只读，只用于查询图标、中英文、是否支持，不会写库
    platform_type: Mapped[Optional["PlatformTypeDefinition"]] = relationship(
        "PlatformTypeDefinition",
        primaryjoin="foreign(Platform.type) == PlatformTypeDefinition.type",
        viewonly=True,
        uselist=False,
        lazy="select"
    )

    def __repr__(self) -> str:
        """String representation of the platform.调试打印"""
        return f"<Platform(id={self.id}, name='{self.name}', type='{self.type}')>"

    @property
    def is_deleted(self) -> bool:
        """Check if the platform is soft deleted. 属性：判断是否软删除"""
        return self.deleted_at is not None

    @property
    def icon(self) -> Optional[str]:
        """Return SVG icon markup for the platform type, when available.
        代理到关联的PlatformTypeDefinition，上层业务直接读取platform.icon，不用手动join
        """
        return self.platform_type.icon if self.platform_type else None

    @property
    def is_supported(self) -> Optional[bool]:
        """Whether this platform type is currently supported.
        代理渠道元数据表is_supported字段，业务层判断该渠道类型是否还被系统支持
        Delegates to the related PlatformTypeDefinition when available.
        """
        return self.platform_type.is_supported if self.platform_type else None

    @property
    def name_en(self) -> Optional[str]:
        """English name of the platform type.
        代理元数据表英文名称
        Delegates to the related PlatformTypeDefinition when available.
        """
        return self.platform_type.name_en if self.platform_type else None


# --- SQLAlchemy event listeners to trigger synchronization ---
# SQLAlchemy ORM事件钩子：ORM完成数据库操作后触发，用来自动触发跨服务同步
# 注意：事件是ORM层面，原生SQL执行不会触发；内部import避免模块循环依赖；吞掉异常，不让同步失败影响主业务DB操作
# 本地数据库已经提交写入成功 ≠ 别的服务知道这条数据存在。
# 两个服务：各有各的数据库，数据库之间没有触发器、没有物理复制。
# 本地数据库 insert/commit，只会改自己库，不会自动远程修改 Platform‑Service 的库。
@event.listens_for(Platform, "after_insert")
def _platform_after_insert(mapper, connection, target: Platform) -> None:
    """ORM插入Platform成功后触发：调用同步服务，把新增渠道同步给Platform Service"""
    try:
        # 函数内部延迟导入，解决模型模块与service模块循环import
        from app.services.platform_sync import trigger_platform_sync
        trigger_platform_sync(str(target.id))
    except Exception:  # pragma: no cover 单元测试忽略这行异常捕获分支
        # 同步任务异常不能抛，不能因为同步失败导致数据库插入回滚；交给后台同步任务重试
        pass


@event.listens_for(Platform, "after_update")
def _platform_after_update(mapper, connection, target: Platform) -> None:
    """ORM更新Platform实体之后触发同步。
    关键点：只在业务字段变更才触发同步；仅仅修改同步状态字段（sync_status/sync_error等）不触发，避免循环触发同步。
    """
    try:
        from app.services.platform_sync import trigger_platform_sync
        # sa_inspect 检查ORM实体哪些字段发生变化
        insp = sa_inspect(target)
        # 获取所有发生变更的字段key集合
        changed = {attr.key for attr in insp.attrs if attr.history.has_changes()}
        # 这些属于同步状态回写字段，变更来自同步任务自身，不需要再次触发同步
        sync_fields = {"sync_status", "last_synced_at", "sync_error", "sync_retry_count"}
        # 没有字段变更 或者 修改的仅仅是同步状态字段，直接return，跳过触发同步
        if not changed or changed.issubset(sync_fields):
            return
        trigger_platform_sync(str(target.id))
    except Exception:  # pragma: no cover
        pass


@event.listens_for(Platform, "after_delete")
def _platform_after_delete(mapper, connection, target: Platform) -> None:
    """ORM删除Platform（含软删除执行db delete）触发，通知平台服务删除对应记录"""
    try:
        from app.services.platform_sync import trigger_platform_delete
        trigger_platform_delete(str(target.id))
    except Exception:  # pragma: no cover
        pass