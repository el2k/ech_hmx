from __future__ import annotations
from pydantic import BaseModel, ConfigDict
from datetime import datetime


class NormalizedMessage(BaseModel):
    source: str
    from_uid: str
    content: str
    # New platform identification fields
    platform_api_key: str
    platform_type: str  # e.g., "email", "wecom", "website"
    platform_id: str    # UUID string of Platform record
    extra: dict | None = None


# VisitorInfo 这个类表示了从 TGO API 返回的访客信息。它包含了访客的核心身份信息、时间戳、状态、个人资料字段以及相关信息。为了适应 API 的增长和变化，允许额外的字段存在。
class VisitorInfo(BaseModel):
    """Visitor representation returned by TGO API.
    Extra fields are allowed to accommodate API growth without breaking.
    """
    model_config = ConfigDict(extra="allow")

    # Core identity
    id: str
    project_id: str
    platform_id: str
    platform_open_id: str

    # Timestamps
    created_at: datetime
    updated_at: datetime
    first_visit_time: datetime
    last_visit_time: datetime
    last_offline_time: datetime | None = None
    deleted_at: datetime | None = None

    # State
    is_online: bool
    platform_type: str | None = None

    # Profile fields
    name: str | None = None
    nickname: str | None = None
    avatar_url: str | None = None
    phone_number: str | None = None
    email: str | None = None
    company: str | None = None
    job_title: str | None = None
    source: str | None = None
    note: str | None = None
    custom_attributes: dict[str, str | None] | None = None

    # Related info (kept flexible)
    tags: list[dict] | None = None
    ai_profile: dict | None = None
    ai_insights: dict | None = None
    system_info: dict | None = None
    recent_activities: list[dict] | None = None

    # Channel info
    channel_id: str | None = None
    channel_type: int | None = None

class ChatCompletionRequest(BaseModel):
    api_key: str
    message: str
    from_uid: str
    # Optional system prompt to steer the assistant
    system_message: str | None = None
    # Desired output format for the assistant response: e.g., "text", "markdown", "html"
    expected_output: str | None = None
    msg_type: int | None = 1
    extra: dict | None = None
    timeout_seconds: int | None = 120


class StreamEvent(BaseModel):
    event: str  # connected/event/error/disconnected
    payload: dict | None = None

