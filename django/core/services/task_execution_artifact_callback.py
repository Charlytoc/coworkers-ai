"""Queue a parent job agent run after an artifact-creator child task finishes."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from django.db import transaction

from core.models import Artifact, JobAssignment, TaskExecution
from core.schemas.task_execution import IdentityConfigSnapshot, TaskExecutionInputs
from core.services.task_execution_queue import enqueue_task_execution

logger = logging.getLogger(__name__)


def enqueue_artifact_creator_callback(
    *,
    task: TaskExecution,
    inputs: TaskExecutionInputs,
    status: Literal["completed", "failed"],
    error_message: str | None = None,
) -> TaskExecution | None:
    if inputs.channel is None or inputs.parent_job_assignment is None:
        logger.info(
            "artifact_creator_callback skip missing_channel_or_parent task=%s",
            task.id,
        )
        return None

    parent_job = JobAssignment.objects.filter(
        id=inputs.parent_job_assignment,
        workspace=task.workspace,
    ).first()
    if parent_job is None:
        logger.warning(
            "artifact_creator_callback skip parent_not_found task=%s parent=%s",
            task.id,
            inputs.parent_job_assignment,
        )
        return None

    artifacts = artifact_callback_payload(task)
    task_instructions = artifact_callback_instructions(
        task=task,
        status=status,
        error_message=error_message,
        artifacts=artifacts,
    )

    parent_cfg = parent_job.get_config()
    identity_snapshot: IdentityConfigSnapshot | None = None
    if parent_cfg.identities:
        first = parent_cfg.identities[0]
        identity_snapshot = IdentityConfigSnapshot(identity=first.id, config=first.config)

    callback_inputs = TaskExecutionInputs(
        task_instructions=task_instructions,
        parent_job_assignment=parent_job.id,
        identity_config=identity_snapshot,
        channel=inputs.channel,
        trigger={
            "type": "artifact_creator_completed",
            "artifact_task_execution_id": str(task.id),
            "status": status,
            "artifact_ids": [a["id"] for a in artifacts],
        },
        variables={
            "artifact_creator": {
                "task_execution_id": str(task.id),
                "name": task.name or "",
                "status": status,
                "error_message": error_message or "",
            },
            "artifacts": artifacts,
        },
    )

    with transaction.atomic():
        locked = TaskExecution.objects.select_for_update().get(id=task.id)
        locked_outputs = dict(locked.outputs or {})
        final_output = dict(locked_outputs.get("final_output") or {})
        existing_id = final_output.get("parent_callback_task_execution_id")
        if existing_id:
            logger.info(
                "artifact_creator_callback already_queued task=%s callback=%s",
                task.id,
                existing_id,
            )
            return TaskExecution.objects.filter(id=existing_id).first()

        callback = TaskExecution(
            workspace=task.workspace,
            job_assignment=parent_job,
            name=f"Artifact result - {task.name or str(task.id)}"[:200],
            status=TaskExecution.Status.QUEUED,
            requires_approval=False,
            scheduled_to=None,
        )
        callback.set_inputs(callback_inputs)
        callback.save()

        final_output["parent_callback_task_execution_id"] = str(callback.id)
        locked_outputs["final_output"] = final_output
        locked.outputs = locked_outputs
        locked.save(update_fields=["outputs", "modified"])

        transaction.on_commit(lambda cid=callback.id: enqueue_task_execution(cid))

    logger.info(
        "artifact_creator_callback queued task=%s callback=%s artifacts=%s",
        task.id,
        callback.id,
        len(artifacts),
    )
    return callback


def artifact_callback_payload(task: TaskExecution) -> list[dict[str, Any]]:
    rows = (
        Artifact.objects.filter(task_execution=task)
        .select_related("media", "identity", "integration_account")
        .order_by("created")
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        media = row.media
        metadata = row.metadata or {}
        item: dict[str, Any] = {
            "id": str(row.id),
            "kind": row.kind,
            "label": row.label or "",
            "created": row.created.isoformat() if row.created else "",
            "metadata": {
                "extension": metadata.get("extension"),
                "mime_type": metadata.get("mime_type"),
                "prompt": metadata.get("prompt"),
            },
            "media": None,
        }
        if row.kind == Artifact.Kind.TEXT:
            text = str(metadata.get("text") or "")
            item["text_preview"] = text[:500]
        if media is not None:
            item["media"] = {
                "id": str(media.id),
                "display_name": media.display_name,
                "mime_type": media.mime_type or "",
                "byte_size": media.byte_size,
                "public_url": media.resolve_public_url(),
            }
        out.append(item)
    return out


def artifact_callback_instructions(
    *,
    task: TaskExecution,
    status: Literal["completed", "failed"],
    error_message: str | None,
    artifacts: list[dict[str, Any]],
) -> str:
    if status == "failed":
        return "\n".join(
            [
                "The background artifact creator failed.",
                f"Artifact task: {task.name or task.id}",
                f"Error: {error_message or 'unknown error'}",
                "Apologize briefly to the user and explain that the work could not be completed.",
            ]
        )
    payload = json.dumps({"artifacts": artifacts}, indent=2, default=str)
    return "\n".join(
        [
            "The background artifact creator finished successfully.",
            f"Artifact task: {task.name or task.id}",
            "Structured artifact summary (JSON):",
            payload,
            "Summarize what was produced for the user in a short, friendly message and send it using the appropriate send tool.",
        ]
    )
