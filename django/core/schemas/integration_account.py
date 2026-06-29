"""Pydantic shapes for ``IntegrationAccount.config`` (per-provider plaintext JSON)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

INTEGRATION_ONBOARDING_CONFIG_KEY = "integration_onboarding"


class SenderApprovalStatus(str, Enum):
    """Lifecycle state of an external sender known to an :class:`IntegrationAccount`.

    ``PENDING``      — seen but not yet cleared (e.g. Telegram waiting for approval code).
    ``NOT_REQUIRED`` — provider has no approval gate (e.g. Instagram DMs today).
    ``APPROVED``     — sender may freely reach the bound jobs on this account.
    """

    PENDING = "pending"
    NOT_REQUIRED = "not_required"
    APPROVED = "approved"


class IntegrationAccountSender(BaseModel):
    """One external counterpart we have observed on an integration account.

    ``external_thread_id`` is the provider identifier used for routing (Telegram ``chat_id``,
    Instagram IGSID, ...).     ``extractions`` is a free-form JSON bag that future agent tools
    (``*.extract_user_context``) can fill with arbitrary data about the counterpart.
    Instagram inbound traffic may set ``instagram_user_profile`` (``username``, ``name`` from Graph).

    ``handle`` is a human-oriented id string for display or future tools (Telegram: ``@username``
    when present, else numeric ``from.id``; Instagram: ``@username`` from the webhook when
    present, otherwise from the Instagram User Profile API for the sender IGSID when allowed).
    """

    model_config = ConfigDict(extra="allow")

    external_thread_id: str
    approval_status: SenderApprovalStatus
    handle: str | None = None
    extractions: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class IntegrationAccountOnboarding(BaseModel):
    """Stored on ``IntegrationAccount.config`` while the default DM job is queued or being generated."""

    model_config = ConfigDict(extra="forbid")

    cyber_identity_id: UUID
    use_case: str = Field(..., max_length=8000)

    @field_validator("use_case")
    @classmethod
    def strip_use_case(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("use_case must not be empty")
        return s


class LlmDefaultJobCopy(BaseModel):
    """Structured output from the onboarding LLM (job copy only)."""

    model_config = ConfigDict(extra="forbid")

    role_name: str = Field(..., max_length=200)
    description: str = Field(..., max_length=2000)
    instructions: str = Field(..., max_length=32000)

    @field_validator("role_name", "description", "instructions")
    @classmethod
    def strip_nonempty(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("field must not be empty")
        return s


class BaseIntegrationAccountConfig(BaseModel):
    """Common shape of ``IntegrationAccount.config`` regardless of provider."""

    model_config = ConfigDict(extra="allow")

    senders: list[IntegrationAccountSender] = Field(default_factory=list)


class TelegramAccountConfig(BaseIntegrationAccountConfig):
    webhook_path_token: str | None = None


class InstagramAuthMethod(str, Enum):
    INSTAGRAM_LOGIN = "instagram_login"
    FACEBOOK_LOGIN = "facebook_login"


class InstagramCapability(str, Enum):
    BASIC = "basic"
    PUBLISH = "publish"
    DM = "dm"
    COMMENTS = "comments"
    INSIGHTS = "insights"
    DELETE = "delete"


class InstagramAccountConfig(BaseIntegrationAccountConfig):
    ig_user_id: str | None = None
    ig_username: str | None = None
    ig_oauth_graph_me_id: str | None = None
    auth_method: InstagramAuthMethod = InstagramAuthMethod.INSTAGRAM_LOGIN
    facebook_page_id: str | None = None
    facebook_page_name: str | None = None
    granted_scopes: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
