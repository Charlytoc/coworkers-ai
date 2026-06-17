"""Pydantic shapes for ``JobAssignment.config`` (JSON targeting + triggers + actions)."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.schemas.channel import Channel


class JobAssignmentEventTrigger(BaseModel):
    """``type: \"event\"`` — ``on`` is a registered integration event slug."""

    model_config = ConfigDict(extra="allow")

    type: Literal["event"]
    on: str
    filter: dict[str, Any] = Field(default_factory=dict)


class JobAssignmentCronTrigger(BaseModel):
    """``type: \"cron\"`` — ``on`` is a cron expression (not validated at API layer yet)."""

    model_config = ConfigDict(extra="allow")

    type: Literal["cron"]
    on: str = ""
    filter: dict[str, Any] = Field(default_factory=dict)


JobAssignmentTrigger = Annotated[
    JobAssignmentEventTrigger | JobAssignmentCronTrigger,
    Field(discriminator="type"),
]


class JobAssignmentActionDirectRecipient(BaseModel):
    """Allowlisted thread for a proactive ``*.send_direct_dm`` action."""

    model_config = ConfigDict(extra="forbid")

    external_thread_id: str
    label: str | None = None


class JobAssignmentAction(BaseModel):
    """One allowed actionable binding (slug + optional integration account)."""

    model_config = ConfigDict(extra="allow")

    actionable_slug: str
    integration_account_id: UUID | None = None
    direct_dm_recipients: list[JobAssignmentActionDirectRecipient] = Field(default_factory=list)


IntegrationAccountProvider = Literal["telegram", "instagram", "gmail"]

class JobAssignmentConfigAccount(BaseModel):
    """Integration account bound to the job (id + provider snapshot)."""

    model_config = ConfigDict(extra="allow")

    id: UUID
    provider: IntegrationAccountProvider


class JobAssignmentConfig(BaseModel):
    """Runtime JSON under ``JobAssignment.config``."""

    model_config = ConfigDict(extra="allow")

    accounts: list[JobAssignmentConfigAccount] = Field(default_factory=list)
    triggers: list[JobAssignmentTrigger] = Field(default_factory=list)
    actions: list[JobAssignmentAction] = Field(default_factory=list)
    channels: list[Channel] = Field(
        default_factory=list,
        description="Snapshotted channels (e.g. Telegram chat) the job can reply through; used by cron-fired tasks.",
    )
    approval_policy: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
