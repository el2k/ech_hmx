"""Setup schemas for system initialization."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import Field, field_validator

from app.schemas.base import BaseSchema

# SetupStatusResponse 是使用 Pydantic 定义的一个响应模型，用于表示系统安装和配置的状态。它包含以下字段：
class SetupStatusResponse(BaseSchema):
    """Response schema for setup status check."""

    is_installed: bool = Field(
        ...,
        description="Whether the system has completed initial installation"
    )
    has_admin: bool = Field(
        ...,
        description="Whether at least one admin account exists"
    )
    has_user_staff: bool = Field(
        ...,
        description="Whether at least one non-admin staff (user role) exists"
    )
    has_llm_config: bool = Field(
        ...,
        description="Whether at least one LLM provider is configured and enabled"
    )
    skip_llm_config: bool = Field(
        ...,
        description="Whether LLM configuration step was explicitly skipped"
    )
    setup_completed_at: Optional[datetime] = Field(
        None,
        description="Timestamp when setup was completed (if applicable)"
    )

# 创建管理员请求模型，用于在系统初始化时创建第一个管理员账户。它包含密码、昵称、项目名称和是否跳过 LLM 配置的字段。
class CreateAdminRequest(BaseSchema):
    """Request schema for creating the first admin account."""

    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Admin password (will be hashed, minimum 8 characters)"
    )
    nickname: Optional[str] = Field(
        None,
        max_length=100,
        description="Admin display name (optional)"
    )
    project_name: str = Field(
        default="Default Project",
        min_length=1,
        max_length=255,
        description="Name for the default project"
    )
    skip_llm_config: bool = Field(
        default=False,
        description="Whether to skip LLM configuration during setup (can be configured later)"
    )

# 创建管理员响应模型，用于返回创建的管理员账户信息，包括 ID、用户名、昵称、关联项目 ID 和项目名称，以及创建时间戳。
class CreateAdminResponse(BaseSchema):
    """Response schema for admin creation."""

    id: UUID = Field(..., description="Created admin staff ID")
    username: str = Field(..., description="Admin username")
    nickname: Optional[str] = Field(None, description="Admin display name")
    project_id: UUID = Field(..., description="Associated project ID")
    project_name: str = Field(..., description="Project name")
    created_at: datetime = Field(..., description="Creation timestamp")

# 配置 LLM 请求模型，用于在系统初始化时配置 LLM 提供商。它包含提供商名称、显示名称、API 密钥、可用模型列表、默认模型、是否启用以及其他提供商特定的配置字段。
class ConfigureLLMRequest(BaseSchema):
    """Request schema for configuring LLM provider."""

    provider: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Provider name (e.g., 'openai', 'anthropic', 'azure_openai', 'dashscope')"
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Display name for this provider configuration"
    )
    api_key: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="API key for the provider (will be encrypted)"
    )
    api_base_url: Optional[str] = Field(
        None,
        max_length=255,
        description="Custom API base URL (optional, for proxies or custom endpoints)"
    )
    available_models: List[str] = Field(
        default_factory=list,
        description="List of available model identifiers"
    )
    default_model: Optional[str] = Field(
        None,
        max_length=100,
        description="Default model to use"
    )
    is_active: bool = Field(
        default=True,
        description="Whether this provider configuration is enabled"
    )
    config: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional provider-specific configuration (e.g., temperature, max_tokens)"
    )

    @field_validator('available_models')
    @classmethod
    def validate_available_models(cls, v: List[str]) -> List[str]:
        """Validate available_models list."""
        if len(v) > 50:
            raise ValueError("Maximum 50 models allowed")
        return v

# 配置 LLM 响应模型，用于返回配置的 LLM 提供商信息，包括 ID、提供商名称、显示名称、默认模型、是否启用、关联项目 ID 和创建时间戳。
class ConfigureLLMResponse(BaseSchema):
    """Response schema for LLM configuration."""

    id: UUID = Field(..., description="AI Provider configuration ID")
    provider: str = Field(..., description="Provider name")
    name: str = Field(..., description="Display name")
    default_model: Optional[str] = Field(None, description="Default model")
    is_active: bool = Field(..., description="Whether this configuration is enabled")
    project_id: UUID = Field(..., description="Associated project ID")
    created_at: datetime = Field(..., description="Creation timestamp")

# SetupCheckResult 是用于表示系统安装和配置验证的单个检查结果的响应模型。它包含一个布尔值字段 passed，表示检查是否通过，以及一个字符串字段 message，提供检查结果的详细信息。
class SetupCheckResult(BaseSchema):
    """Individual check result for setup verification."""

    passed: bool = Field(..., description="Whether the check passed")
    message: str = Field(..., description="Check result message")

# 验证安装响应模型，用于返回系统安装和配置验证的结果。它包含一个布尔值字段 is_valid，表示安装是否有效和完整，一个字典字段 checks，包含各个检查的结果，以及两个列表字段 errors 和 warnings，分别列出发现的错误和警告信息。
class VerifySetupResponse(BaseSchema):
    """Response schema for setup verification."""

    is_valid: bool = Field(
        ...,
        description="Whether the installation is valid and complete"
    )
    checks: Dict[str, SetupCheckResult] = Field(
        ...,
        description="Individual check results"
    )
    errors: List[str] = Field(
        default_factory=list,
        description="List of errors found"
    )
    warnings: List[str] = Field(
        default_factory=list,
        description="List of warnings"
    )



# SkipLLMConfigResponse 是用于在系统初始化过程中跳过 LLM 配置的响应模型。它包含一个字符串字段 message，提供跳过 LLM 操作的成功消息，一个布尔值字段 is_installed，表示跳过 LLM 配置后系统的安装状态，以及一个 datetime 字段 setup_completed_at，记录设置标记为完成的时间戳。
class SkipLLMConfigResponse(BaseSchema):
    """Response schema for skipping LLM configuration during setup."""

    message: str = Field(..., description="Success message for skip LLM operation")
    is_installed: bool = Field(
        ...,
        description="Updated installation status after skipping LLM configuration",
    )
    setup_completed_at: datetime = Field(
        ...,
        description="Timestamp when setup was marked as completed",
    )

# StaffCreateItem 是用于批量创建员工成员的单个员工项的请求模型。它包含用户名、密码、真实姓名、显示名称和描述字段，用于在系统初始化过程中创建员工账户。
class StaffCreateItem(BaseSchema):
    """Single staff item for batch creation."""

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        description="Staff username for login (unique)"
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Staff password (will be hashed)"
    )
    name: Optional[str] = Field(
        None,
        max_length=100,
        description="Staff real name"
    )
    nickname: Optional[str] = Field(
        None,
        max_length=100,
        description="Staff display name"
    )
    description: Optional[str] = Field(
        None,
        max_length=500,
        description="Staff description for LLM assignment"
    )

# BatchCreateStaffRequest 是用于在系统初始化过程中批量创建员工成员的请求模型。它包含一个 staff_list 字段，该字段是一个 StaffCreateItem 对象的列表，表示要创建的员工成员列表，最多可以包含 100 个员工。
class BatchCreateStaffRequest(BaseSchema):
    """Request schema for batch creating staff members during setup."""

    staff_list: List[StaffCreateItem] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of staff members to create (max 100)"
    )

# StaffCreatedItem 是用于表示已创建的员工项的响应模型。它包含员工的 ID、用户名、真实姓名、显示名称和创建时间戳字段，用于在批量创建员工成员后返回已创建的员工信息。
class StaffCreatedItem(BaseSchema):
    """Created staff item response."""

    id: UUID = Field(..., description="Staff ID")
    username: str = Field(..., description="Staff username")
    name: Optional[str] = Field(None, description="Staff real name")
    nickname: Optional[str] = Field(None, description="Staff display name")
    created_at: datetime = Field(..., description="Creation timestamp")

# BatchCreateStaffResponse 是用于在系统初始化过程中批量创建员工成员的响应模型。它包含已创建员工的数量、已创建员工的列表以及跳过的用户名列表，用于返回批量创建员工操作的结果。
class BatchCreateStaffResponse(BaseSchema):
    """Response schema for batch staff creation."""

    created_count: int = Field(..., description="Number of staff members created")
    staff_list: List[StaffCreatedItem] = Field(..., description="List of created staff members")
    skipped_usernames: List[str] = Field(
        default_factory=list,
        description="Usernames that were skipped (already exist)"
    )
