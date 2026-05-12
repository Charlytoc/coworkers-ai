"""Shared path from a selected inbound DM job to a queued agent task execution."""

from __future__ import annotations

from typing import Any

from core.models import IntegrationAccount, JobAssignment
from core.services.conversations import append_user_message, get_or_create_active_conversation
from core.services.job_task_processor_agent import JobTaskProcessorAgent
from core.services.task_execution_queue import enqueue_task_execution
from core.services.task_execution_runner import create_queued_event_task_execution


def enqueue_inbound_dm_task_execution(
    *,
    job: JobAssignment,
    account: IntegrationAccount,
    external_thread_id: str,
    external_user_id: str,
    text: str,
    event_slug: str,
    structured_message: dict[str, Any],
    empty_text_instructions: str,
) -> bool:
    identity = JobTaskProcessorAgent.primary_identity_for_job(job)
    if identity is None:
        return False

    convo = get_or_create_active_conversation(
        account=account,
        cyber_identity=identity,
        external_thread_id=external_thread_id,
        external_user_id=external_user_id,
    )

    user_msg = append_user_message(
        convo,
        content_text=text,
        content_structured=structured_message,
    )

    channel = JobTaskProcessorAgent.integration_channel_for_thread(account, external_thread_id)
    if channel is None:
        return False

    instructions = text if text else empty_text_instructions
    task_ex = create_queued_event_task_execution(
        job=job,
        task_instructions=instructions,
        channel=channel,
        event_slug=event_slug,
        conversation_id=convo.id,
        triggering_message_id=user_msg.id,
    )
    enqueue_task_execution(task_ex.id)
    return True
