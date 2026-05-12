"""Persist agent session logs and task execution outcomes after a run."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from core.agent.base import AgentLoopSummary
from core.models import Conversation, JobAssignment, TaskExecution
from core.models.agent_session_log import AgentSessionLog
from core.schemas.task_execution import (
    ArtifactRef,
    TaskExecutionError,
    TaskExecutionInputs,
    TaskExecutionOutputs,
)
from core.services.task_execution_artifact_callback import enqueue_artifact_creator_callback

logger = logging.getLogger(__name__)


def persist_successful_agent_run(
    *,
    task: TaskExecution,
    job: JobAssignment,
    conversation: Conversation,
    log: AgentSessionLog,
    summary: AgentLoopSummary,
    duration: float,
    trigger_dict: dict[str, Any] | None,
    is_event: bool,
    trigger_type: str,
    inputs: TaskExecutionInputs,
) -> dict[str, Any]:
    log.status = AgentSessionLog.Status.ERROR if summary.error else AgentSessionLog.Status.COMPLETED
    log.iterations = summary.iterations
    log.tool_calls_count = summary.tool_calls_count
    log.total_duration = round(duration, 3)
    log.ended_at = datetime.now(timezone.utc)
    log.outputs = {
        "final_response": summary.final_response or "",
        "messages": [m.model_dump() for m in summary.messages],
        "task_execution_id": str(task.id),
        "job_assignment_id": str(job.id),
        "conversation_id": str(conversation.id),
    }
    if trigger_dict and is_event:
        tid = trigger_dict.get("triggering_message_id")
        if tid:
            log.outputs["triggering_message_id"] = str(tid)
    if summary.error:
        log.error_message = summary.error
    log.save()

    artifact_refs = [
        ArtifactRef(id=a.id, kind=a.kind, label=a.label)
        for a in task.artifacts.all().order_by("created")
    ]
    outputs = TaskExecutionOutputs(
        artifacts=artifact_refs,
        total_duration_ms=int(duration * 1000),
        agent_session_log=log.id,
        error=TaskExecutionError(message=summary.error) if summary.error else None,
    )
    task.set_outputs(outputs)
    task.status = TaskExecution.Status.FAILED if summary.error else TaskExecution.Status.COMPLETED
    task.completed_at = datetime.now(timezone.utc)
    task.save(update_fields=["status", "outputs", "completed_at", "modified"])

    if trigger_type == "artifact_creator" and summary.error:
        enqueue_artifact_creator_callback(
            task=task,
            inputs=inputs,
            error_message=summary.error,
        )

    return {
        "status": "completed" if not summary.error else "error",
        "task_execution_id": str(task.id),
        "agent_session_log_id": str(log.id),
    }


def persist_failed_agent_run(
    *,
    task: TaskExecution,
    log: AgentSessionLog,
    duration: float,
    error_message: str,
    error_type: str | None,
    trigger_type: str,
    inputs: TaskExecutionInputs,
) -> dict[str, Any]:
    log.status = AgentSessionLog.Status.ERROR
    log.error_message = error_message
    log.total_duration = round(duration, 3)
    log.ended_at = datetime.now(timezone.utc)
    log.save()
    logger.exception("run_task_execution failed task=%s", task.id)
    outputs = TaskExecutionOutputs(
        total_duration_ms=int(duration * 1000),
        agent_session_log=log.id,
        error=TaskExecutionError(message=error_message, type=error_type),
    )
    task.set_outputs(outputs)
    task.status = TaskExecution.Status.FAILED
    task.completed_at = datetime.now(timezone.utc)
    task.save(update_fields=["status", "outputs", "completed_at", "modified"])
    if trigger_type == "artifact_creator":
        enqueue_artifact_creator_callback(
            task=task,
            inputs=inputs,
            error_message=error_message,
        )
    return {"status": "error", "error": error_message}
