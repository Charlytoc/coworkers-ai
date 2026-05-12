"""Shapes for outbound DM send targets (agent send tools + prompt hints)."""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SendTargetProvider(str, Enum):
    WEB_CHAT = "web_chat"
    TELEGRAM = "telegram"
    INSTAGRAM = "instagram"


class SendTargetPublic(BaseModel):
    """Subset exposed to the model in the system prompt (no raw ids or thread ids)."""

    model_config = ConfigDict(extra="forbid")

    target_index: int = Field(ge=0)
    target_role: str
    integration_type: SendTargetProvider


class SendTargetResolution(BaseModel):
    """Output of :func:`core.services.send_targets.resolve_send_target` (no index / role)."""

    model_config = ConfigDict(extra="forbid")

    provider: SendTargetProvider
    integration_account_id: uuid.UUID | None = None
    external_thread_id: str = ""
    web_user_id: int | None = None


class ResolvedSendTarget(BaseModel):
    """One indexed row passed into send tools (internal + prompt projection)."""

    model_config = ConfigDict(extra="forbid")

    target_index: int = Field(ge=0)
    target_role: str
    provider: SendTargetProvider
    integration_account_id: uuid.UUID | None = None
    external_thread_id: str = ""
    web_user_id: int | None = None
    target_kind: Literal["reply", "direct"] | None = None

    def to_public(self) -> SendTargetPublic:
        return SendTargetPublic(
            target_index=self.target_index,
            target_role=self.target_role,
            integration_type=self.provider,
        )
