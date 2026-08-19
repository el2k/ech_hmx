"""
Base model class and common database utilities.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    """Base class for all database models."""

    pass

# 将“创建时间”和“更新时间”这两个通用字段进行模块化封装
class TimestampMixin:
    created_at:Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        # timezone=True 表示存储带时区的时间
        server_default=func.current_timestamp(),
        nullable=False,
        doc="Record creation timestamp",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
        doc="Record last update timestamp",
    )

# 定义了 SQLAlchemy 中用于实现软删除（Soft Delete）功能
# 软删除的核心思想是：不真正从数据库中物理删除数据，而是通过更新一个标记字段来标识该数据“已删除”。这能有效防止误删、支持数据恢复，并保留审计历史记录
class SoftDeleteMixin:
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Record deletion timestamp (NULL if not deleted)",
    )
    @property
    def is_deleted(self)->bool:
        "检查是否已经删除数据,非空写入时间则表示已经删除"
        return self.deleted_at is not None

    def soft_delete(self)->None:
        "标记数据为已删除"
        self.deleted_at = datetime.now(timezone.utc)

    def restore(self)->None:
        "恢复已删除的数据"
        self.deleted_at = None

# 使用 UUID 作为主键”这一通用需求进行模块化封装。
# 相比于传统的自增整数（Auto-Increment Integer）主键，UUID 在分布式系统、微服务架构以及对外暴露 API 时具有更高的安全性和扩展性。
class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), 
        # as_uuid=True：这是关键参数。它告诉 SQLAlchemy 在从数据库读取数据时，
        # 自动将数据库底层的 UUID 格式转换为 Python 的 uuid.UUID 对象；
        # 在写入时，再将其转换为数据库能识别的格式。如果不加这个参数，返回的可能是普通的字符串。
        primary_key=True,
        default=uuid.uuid4,
        doc="Primary key as UUID",
    )

# 这段代码实现了一个将 SQLAlchemy ORM 模型实例转换为普通 Python 字典的通用工具函数。
# 这在 Web 开发中非常常见，主要用于将数据库对象序列化为 JSON 格式返回给前端，或者用于日志记录等场景。
def to_dict(obj: Any, exclude: Optional[set]=None) -> Dict[str,Any]:
    # obj: Any：接收任意类型的对象，通常传入的是 SQLAlchemy 的模型实例（如 User）。
    # exclude: Optional[set] = None：提供一个可选的集合参数，允许调用者指定需要排除的字段名（例如密码、敏感信息等）。
    exclude = exclude or set()
    result = {}
    # 遍历模型列并提取数据
    # obj.__table__.columns：这是 SQLAlchemy 的核心元数据属性。
    # 它获取该模型对应的数据库表的所有列定义，而不是 Python 类的所有属性（这样可以自动排除掉 Python 类上定义的方法、关系属性等）
    for column in obj.__table__.columns:
        if column.name not in exclude:
            value = getattr(obj, column.name)  # getattr(obj, column.name)：动态获取该实例上对应列的实际值。
            if isinstance(value, datetime):
                value = value.isoformat()  # 如果值是 datetime 类型，将其转换为 ISO 格式的字符串，方便序列化。
            elif isinstance(value, uuid.UUID):
                value = str(value)  # 如果值是 UUID 类型，将其转换为字符串，方便序列化。
            result[column.name] = value
    return result

def from_dict(model_class: type, data: Dict[str, Any]) -> Any:
    # 将字典数据转换为 SQLAlchemy ORM 模型实例的通用工具函数。
    # Filter out keys that don't exist as columns
    valid_columns = {column.name for column in model_class.__table__.columns}
    filtered_data = {k: v for k, v in data.items() if k in valid_columns}
    
    return model_class(**filtered_data)
