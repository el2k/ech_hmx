"""Visitor tag model."""
# 访客‑标签中间关联表：实现 Visitor（访客） ↔ Tag（标签）的**多对多关系**
# 一个访客可以打多个标签；同一个标签可以被打给多个访客；本表支持软删除
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class VisitorTag(Base):
    """Visitor tag model for many‑to‑many relationship between visitors and tags.
    访客与标签的多对多中间表。
    注意：不是SQLAlchemy简单secondary中间表，这是一张**带业务字段的实体中间表**，拥有主键、时间戳、软删除。
    给访客打标签等价于插入VisitorTag记录；取消标签优先使用软删除，不直接物理DELETE行。
    """

    __tablename__ = "api_visitor_tags"

    # ========== 主键 ==========
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    """中间表独立UUID主键；因为带附加业务字段，不使用复合主键"""

    # ========== 外键字段 ==========
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_projects.id", ondelete="CASCADE"),
        nullable=False,
        comment="Associated project ID for multi‑tenant isolation"
    )
    """
    租户ID，多租户隔离。
    ondelete="CASCADE"：租户删除，数据库级联删除该租户全部访客标签关联记录。
    """

    visitor_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_visitors.id"),
        nullable=False,
        comment="Associated visitor ID"
    )
    """关联访客主键ID；外键未设置ondelete=CASCADE"""

    tag_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("api_tags.id"),
        nullable=False,
        comment="Associated tag ID (Base64 encoded)"
    )
    """
    关联标签ID；注意此字段类型是字符串，Base64编码，不是UUID。
    外键指向 api_tags 标签主表主键。
    """

    # ========== 时间戳 ==========
    created_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        comment="Creation timestamp"
    )
    """关联记录创建时间，即给访客打上该标签的时间"""

    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
        comment="Last update timestamp"
    )
    """记录更新时间，软删除时会触发更新"""

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        nullable=True,
        comment="Soft deletion timestamp"
    )
    """软删除时间戳；非NULL代表该标签已从访客身上移除（逻辑删除）"""

    # ========== ORM双向关系 ==========
    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="visitor_tags",
        lazy="select"
    )
    """反向关联租户Project；Project模型中 visitor_tags 集合映射本表"""

    visitor: Mapped["Visitor"] = relationship(
        "Visitor",
        back_populates="visitor_tags",
        lazy="select"
    )
    """反向关联访客Visitor；Visitor模型的 visitor_tags 拿到该访客所有标签关联记录"""

    tag: Mapped["Tag"] = relationship(
        "Tag",
        back_populates="visitor_tags",
        lazy="select"
    )
    """反向关联标签Tag；Tag模型的 visitor_tags 拿到所有被打上该标签的访客关联记录"""

    # ========== 表级约束 ==========
    __table_args__ = (
        UniqueConstraint(
            "visitor_id", "tag_id",
            name="uk_api_visitor_tags_visitor_tag"
        ),
    )
    """
    联合唯一约束：同一个访客+同一个标签，只能存在一条有效关联。
    防止重复给同一个访客重复打上完全一样的标签；
    注意：软删除(deleted_at不为null)的行依然占用唯一索引，业务要规避。
    """

    def __repr__(self) -> str:
        """调试日志打印对象信息"""
        return (
            f"<VisitorTag(id={self.id}, "
            f"visitor_id={self.visitor_id}, "
            f"tag_id='{self.tag_id}')>"
        )

    @property
    def is_deleted(self) -> bool:
        """Check if the visitor tag is soft deleted.
        只读属性，判断该标签关联是否已经逻辑移除。
        """
        return self.deleted_at is not None