"""Durable conversation between a ``CyberIdentity`` and an external counterpart on one integration account."""

from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from model_utils.models import TimeStampedModel

from core.models.cyber_identity import CyberIdentity
from core.models.integration_account import IntegrationAccount
from core.models.workspace import Workspace
from core.schemas.conversation import ConversationConfig


class Conversation(TimeStampedModel):
    """A workspace conversation thread.

    A conversation is always bound to **one** :class:`IntegrationAccount` (the channel used
    to reach the counterpart). The external thread/user ids and any future per-conversation
    knobs live in :pyattr:`config` (validated via :class:`core.schemas.conversation.ConversationConfig`).
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        ARCHIVED = "archived", "Archived"
        DELETED = "deleted", "Deleted"

    class Origin(models.TextChoices):
        INTEGRATION = "integration", "Integration"
        WEB = "web", "Web chat"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    origin = models.CharField(
        max_length=20,
        choices=Origin.choices,
        default=Origin.INTEGRATION,
        help_text="Where this conversation happens (an external integration vs. the in-app web chat).",
    )
    integration_account = models.ForeignKey(
        IntegrationAccount,
        on_delete=models.CASCADE,
        related_name="conversations",
        null=True,
        blank=True,
        help_text="Channel this conversation lives on (Telegram bot, Instagram account, ...). "
        "Null for web-chat conversations.",
    )
    cyber_identity = models.ForeignKey(
        CyberIdentity,
        on_delete=models.CASCADE,
        related_name="conversations",
        help_text="Persona on our side that speaks in this conversation.",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Validated against ConversationConfig: external_thread_id, external_user_id, ...",
    )

    last_interaction_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the last message (denormalized; updated on message write).",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-last_interaction_at", "-created")
        indexes = [
            models.Index(fields=("workspace", "status", "-last_interaction_at")),
            models.Index(fields=("integration_account", "-last_interaction_at")),
            models.Index(fields=("cyber_identity", "-last_interaction_at")),
        ]

    def __str__(self) -> str:
        return f"Conversation {self.pk} [{self.get_status_display()}]"

    def clean(self) -> None:
        super().clean()
        if self.config is not None and not isinstance(self.config, dict):
            raise ValidationError({"config": "Must be a JSON object (dict)."})
        if self.integration_account_id and self.workspace_id and self.integration_account.workspace_id != self.workspace_id:
            raise ValidationError("integration_account must belong to the same workspace as the conversation.")
        if self.cyber_identity_id and self.workspace_id and self.cyber_identity.workspace_id != self.workspace_id:
            raise ValidationError("cyber_identity must belong to the same workspace as the conversation.")
        try:
            cfg = ConversationConfig.model_validate(self.config or {})
        except Exception as exc:
            raise ValidationError({"config": str(exc)}) from exc

        if self.origin == self.Origin.INTEGRATION:
            if not self.integration_account_id:
                raise ValidationError(
                    {"integration_account": "Required when origin='integration'."}
                )
            if not cfg.external_thread_id or not cfg.external_user_id:
                raise ValidationError(
                    {"config": "external_thread_id and external_user_id are required when origin='integration'."}
                )
        elif self.origin == self.Origin.WEB:
            if self.integration_account_id:
                raise ValidationError(
                    {"integration_account": "Must be null when origin='web'."}
                )
            if cfg.web_user_id is None:
                raise ValidationError(
                    {"config": "web_user_id is required when origin='web'."}
                )
            if cfg.job_assignment_id is None:
                raise ValidationError(
                    {"config": "job_assignment_id is required when origin='web'."}
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def get_config(self) -> ConversationConfig:
        return ConversationConfig.model_validate(self.config or {})

    def set_config(self, config: ConversationConfig) -> None:
        self.config = config.model_dump(mode="json")
