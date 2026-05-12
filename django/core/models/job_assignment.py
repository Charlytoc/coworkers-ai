"""Job the agent takes on: role, triggers, and which actionables it may use."""

from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from model_utils.models import TimeStampedModel

from core.models.workspace import Workspace
from core.schemas.job_assignment import JobAssignmentConfig


class JobAssignment(TimeStampedModel):
    """A durable "job" a workspace agent performs, bound to triggers and allowed actionables.

    Runtime targeting (accounts, identities, triggers, actions, approval policy, optional
    output schema) lives under ``config`` as a flexible JSON object; the rough shape is::

        {
          "accounts": [{"id": "<IntegrationAccount.uuid>", "provider": "telegram"|...}, ...],
          "identities": [{"id": "<CyberIdentity.uuid>", "type": "<CyberIdentity.type>", "config": {...}}, ...],
          "triggers": [
            {"type": "event"|"cron", "on": "<event_slug or cron>", "filter": {...}}
          ],
          "actions": [
            {"actionable_slug": "telegram.reply_dm", "integration_account_id": "<uuid>"}
          ],
          "approval_policy": {...},
          "output_schema": {...}   # optional json schema
        }
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="job_assignments",
    )

    role_name = models.CharField(
        max_length=200,
        help_text="Role the agent plays, e.g. 'Telegram Personal Assistant'. Used for display and logging.",
    )
    description = models.TextField(
        blank=True,
        help_text="What this job does, in plain text. Action it usually takes, accounts that are involved, etc.",
    )
    instructions = models.TextField(
        blank=True,
        help_text="Detailed instructions so the agent understands how to perform this job at runtime. Appended to task specific instructions.",
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Targeting + runtime policy: accounts [{id, provider}], identities [{id, type, config}], triggers, actions, approval_policy, optional output_schema. Can be overridden at task execution level.",
    )
    enabled = models.BooleanField(default=True)
    parent_job_assignment = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_job_assignments",
        help_text="If this job was spawned by another job (e.g. an AI assistant that created a routine), this points to it.",
    )

    class Meta:
        ordering = ("workspace_id", "role_name")
        indexes = [
            models.Index(fields=("workspace", "enabled")),
            models.Index(fields=("parent_job_assignment",)),
        ]

    def __str__(self) -> str:
        return self.role_name

    def clean(self) -> None:
        super().clean()
        if self.config is not None and not isinstance(self.config, dict):
            raise ValidationError({"config": "Must be a JSON object (dict)."})

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

    def get_config(self) -> JobAssignmentConfig:
        return JobAssignmentConfig.model_validate(self.config)

    def set_config(self, config: JobAssignmentConfig) -> None:
        self.config = config.model_dump(mode="json")
