"""Durable output/resource produced by the workspace or by an external provider."""

from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from model_utils.models import TimeStampedModel

from core.models.cyber_identity import CyberIdentity
from core.models.integration_account import IntegrationAccount
from core.models.media_object import MediaObject
from core.models.task_execution import TaskExecution
from core.models.workspace import Workspace


class Artifact(TimeStampedModel):
    """A durable workspace output, either generated internally or created in an external provider."""

    class Kind(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"
        AUDIO = "audio", "Audio"
        DOCUMENT = "document", "Document"
        TEXT = "text", "Text"
        EXTERNAL_RESOURCE = "external_resource", "External resource"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="artifacts",
    )
    task_execution = models.ForeignKey(
        TaskExecution,
        on_delete=models.CASCADE,
        related_name="artifacts",
        null=True,
        blank=True,
    )
    identity = models.ForeignKey(
        CyberIdentity,
        on_delete=models.SET_NULL,
        related_name="artifacts",
        null=True,
        blank=True,
    )
    media = models.ForeignKey(
        MediaObject,
        on_delete=models.PROTECT,
        related_name="artifacts",
        null=True,
        blank=True,
    )
    integration_account = models.ForeignKey(
        IntegrationAccount,
        on_delete=models.CASCADE,
        related_name="artifacts",
        null=True,
        blank=True,
    )

    kind = models.CharField(max_length=32, choices=Kind.choices)
    label = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Per-kind metadata such as text, extension, provider ids, prompts, dimensions, "
            "or publish timestamps."
        ),
    )

    class Meta:
        ordering = ("workspace_id", "kind", "-created")
        indexes = [
            models.Index(fields=("workspace", "kind", "-created")),
            models.Index(fields=("workspace", "identity", "-created")),
            models.Index(fields=("task_execution", "kind")),
            models.Index(fields=("integration_account", "kind")),
        ]

    def __str__(self) -> str:
        return f"Artifact {self.pk} ({self.get_kind_display()})"

    def clean(self) -> None:
        super().clean()
        if self.metadata is not None and not isinstance(self.metadata, dict):
            raise ValidationError({"metadata": "Must be a JSON object (dict)."})

        if (
            self.task_execution_id
            and self.workspace_id
            and self.task_execution.workspace_id != self.workspace_id
        ):
            raise ValidationError(
                "Task execution must belong to the same workspace as the artifact."
            )
        if (
            self.task_execution_id
            and self.media_id
            and self.task_execution.workspace_id != self.media.workspace_id
        ):
            raise ValidationError(
                "Media must belong to the same workspace as the task execution."
            )
        if (
            self.media_id
            and self.workspace_id
            and self.media.workspace_id != self.workspace_id
        ):
            raise ValidationError(
                {"media": "Media must belong to the same workspace as the artifact."}
            )
        if (
            self.identity_id
            and self.workspace_id
            and self.identity.workspace_id != self.workspace_id
        ):
            raise ValidationError(
                {"identity": "Identity must belong to the same workspace as the artifact."}
            )
        if (
            self.integration_account_id
            and self.workspace_id
            and self.integration_account.workspace_id != self.workspace_id
        ):
            raise ValidationError(
                {
                    "integration_account": (
                        "Integration account must belong to the same workspace as the artifact."
                    )
                }
            )

        if self.kind == self.Kind.EXTERNAL_RESOURCE:
            errors: dict[str, str] = {}
            if not self.integration_account_id:
                errors["integration_account"] = "External resource artifacts require an integration account."
            external_resource_id = str(
                (self.metadata or {}).get("external_resource_id") or ""
            ).strip()
            resource_type = str((self.metadata or {}).get("resource_type") or "").strip()
            if not external_resource_id:
                errors["metadata.external_resource_id"] = "External resource id is required."
            if not resource_type:
                errors["metadata.resource_type"] = "Resource type is required."
            if errors:
                raise ValidationError(errors)

        if self.kind == self.Kind.TEXT:
            text = (self.metadata or {}).get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValidationError(
                    {"metadata.text": "Text artifacts require non-empty metadata.text."}
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
