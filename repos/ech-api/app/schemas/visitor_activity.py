"""Schemas for visitor activity logging."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema


class VisitorActivityType(str, Enum):
    """Supported visitor activity types."""
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    PAGE_VIEW = "page_view"
    MESSAGE_SENT = "message_sent"
    FORM_SUBMITTED = "form_submitted"
    FILE_UPLOADED = "file_uploaded"
    CUSTOM_EVENT = "custom_event"


class VisitorActivityContext(BaseSchema):
    """Structured context payload for an activity."""

    page_url: Optional[str] = Field(
        None,
        description="Full URL associated with the activity, such as a visited page.",
        example="https://example.com/pricing",
    )
    referrer: Optional[str] = Field(
        None,
        description="Referrer URL or source identifier.",
        example="https://google.com/search?q=example",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key/value data related to the activity.",
        example={"cta": "start-chat", "browser": "Chrome 124"},
    )


class VisitorActivityCreateRequest(BaseSchema):
    """Incoming payload to record a visitor activity."""

    id: Optional[UUID] = Field(
        None,
        description="Existing activity ID to update; omit to create a new record.",
        example="6f90a4e3-01d4-4c3f-970a-c90e7ec0d235",
    )
    platform_api_key: Optional[str] = Field(
        None,
        min_length=10,
        description="Platform API key used for authentication (may also be provided via `X-Platform-API-Key` header).",
        example="plf_3b9f86e5d1c946e08b9f2f51234abcd1",
    )
    visitor_id: UUID = Field(
        ...,
        description="Visitor ID returned by the registration API.",
        example="9a5d86c4-1d3a-4f4b-bad0-0d81c3f9f1a2",
    )
    activity_type: VisitorActivityType = Field(
        ...,
        description="Categorised type of the activity being recorded.",
        example=VisitorActivityType.PAGE_VIEW,
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Short headline summarising the activity.",
        example="Visited pricing page",
    )
    description: Optional[str] = Field(
        None,
        description="Optional longer description for the activity.",
        example="The visitor opened the pricing page and viewed the enterprise plan details.",
    )
    duration_seconds: Optional[int] = Field(
        None,
        ge=0,
        description="Duration the visitor spent on the activity, in seconds.",
        example=42,
    )
    context: Optional[VisitorActivityContext] = Field(
        None,
        description="Structured context for the activity.",
        examples=[
            {
                "page_url": "https://example.com/pricing",
                "referrer": "https://google.com",
                "metadata": {
                    "cta": "start-chat",
                    "device": "iPhone 15",
                    "app_version": "1.4.2",
                },
            }
        ],
    )
    occurred_at: Optional[datetime] = Field(
        None,
        description="Timestamp when the activity happened. Defaults to now if omitted.",
        example="2024-06-01T08:30:15.123Z",
    )


class VisitorActivityCreateResponse(BaseSchema):
    """Response after recording a visitor activity."""

    id: UUID = Field(..., description="Recorded activity ID.")
    activity_type: str = Field(..., description="Stored activity type.")
    title: str = Field(..., description="Stored activity title.")
    description: Optional[str] = Field(None, description="Stored activity description.")
    occurred_at: datetime = Field(..., description="Timestamp the activity is recorded at.")
    duration_seconds: Optional[int] = Field(None, description="Stored activity duration in seconds.")
    context: Optional[Dict[str, Any]] = Field(None, description="Persisted activity context.")
