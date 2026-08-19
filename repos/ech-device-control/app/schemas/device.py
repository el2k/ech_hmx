"""Device-related Pydantic schemas."""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# 设备类型
class DeviceType(str, Enum):
    """Device type enumeration."""

    DESKTOP = "desktop"
    MOBILE = "mobile"

# 设备状态
class DeviceStatus(str, Enum):
    """Device status enumeration."""

    ONLINE = "online"
    OFFLINE = "offline"

# 设备基础信息
class DeviceBase(BaseModel):
    """Base device schema."""

    device_name: str = Field(..., description="Device name")
    device_type: DeviceType = Field(default=DeviceType.DESKTOP)
    os: str = Field(..., description="Operating system")
    os_version: Optional[str] = Field(None, description="OS version")
    screen_resolution: Optional[str] = Field(None, description="Screen resolution")

# 设备创建请求
class DeviceCreateRequest(DeviceBase):
    """Request schema for creating a device."""

    pass

# 设备更新请求
class DeviceUpdateRequest(BaseModel):
    """Request schema for updating a device."""

    device_name: Optional[str] = None

# 设备响应
class DeviceResponse(DeviceBase):
    """Response schema for a device."""

    id: UUID
    project_id: UUID
    status: DeviceStatus
    last_seen_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

# 设备列表响应
class DeviceListResponse(BaseModel):
    """Response schema for device list."""

    devices: List[DeviceResponse]
    total: int

# 绑定码响应
class BindCodeResponse(BaseModel):
    """Response schema for bind code generation."""

    bind_code: str = Field(..., description="6-digit bind code")
    expires_at: datetime = Field(..., description="Expiration time")

# 设备注册请求
class DeviceRegistrationRequest(BaseModel):
    """Request schema for device registration via WebSocket."""

    device_name: str
    device_type: DeviceType = DeviceType.DESKTOP
    os: str
    os_version: Optional[str] = None
    screen_resolution: Optional[str] = None
    bind_code: str

# 设备注册响应
class DeviceRegistrationResponse(BaseModel):
    """Response schema for device registration."""

    success: bool
    device_id: Optional[UUID] = None
    device_token: Optional[str] = None
    error: Optional[str] = None
