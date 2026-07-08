"""Agent-authored long-term memory for a ``CyberIdentity`` (core memories + on-demand knowledge)."""

from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from model_utils.models import TimeStampedModel

from core.models.cyber_identity import CyberIdentity


class Memory(TimeStampedModel):
    """
    Agent-authored text memory, linked to a ``CyberIdentity`` and/or a ``JobAssignment``.

    Both links are nullable but **at least one must be set** (enforced by a DB constraint and
    :meth:`clean`). This lets memories survive an identity swap on a job (kept via the job link) and
    lets an identity's learnings carry into future jobs (kept via the identity link). A memory
    written during a run is linked to both the running job and its identity when available.

    - ``CORE`` memories are always injected into the agent prompt for in-scope runs.
    - ``KNOWLEDGE`` memories are retrieved on demand (e.g. by topic) while the agent executes a task.
    """

    class MemoryType(models.TextChoices):
        CORE = "core", "Core"
        KNOWLEDGE = "knowledge", "Knowledge"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    identity = models.ForeignKey(
        CyberIdentity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memories",
        help_text="Persona that owns this memory; preserved across the jobs that use this identity.",
    )
    job_assignment = models.ForeignKey(
        "core.JobAssignment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memories",
        help_text="Job this memory was learned in; preserved even if the job's identity later changes.",
    )

    memory_type = models.CharField(
        max_length=20,
        choices=MemoryType.choices,
        default=MemoryType.KNOWLEDGE,
    )
    content = models.TextField(help_text="The memory text to inject or retrieve.")
    source = models.TextField(
        blank=True,
        help_text="Short explanation of why the agent stored this memory (context, task, etc.).",
    )
    topics = models.JSONField(
        default=list,
        blank=True,
        help_text="Topic tags as a list of strings; used to retrieve knowledge memories by topic.",
    )

    class Meta:
        ordering = ("-created",)
        indexes = [
            models.Index(fields=("identity", "memory_type", "-created")),
            models.Index(fields=("job_assignment", "memory_type", "-created")),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(identity__isnull=False) | models.Q(job_assignment__isnull=False),
                name="memory_identity_or_job_required",
            ),
        ]

    def __str__(self) -> str:
        preview = (self.content or "").strip().splitlines()[0][:60] if self.content else str(self.pk)
        return f"[{self.get_memory_type_display()}] {preview}"

    def clean(self) -> None:
        super().clean()
        if not (self.content or "").strip():
            raise ValidationError({"content": "Memory content cannot be empty."})
        if self.identity_id is None and self.job_assignment_id is None:
            raise ValidationError("A memory must be linked to an identity, a job assignment, or both.")
        _validate_topics(self.topics)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


def _validate_topics(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise ValidationError({"topics": "Must be a JSON array of strings."})
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError({"topics": "Each topic must be a non-empty string."})
