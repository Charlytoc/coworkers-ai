"""Web chat entry point. Runs through the unified JobAssignment + Conversation pipeline.

A message POSTed here requires a ``job_assignment_id`` for an enabled workspace job with at least
one cyber identity. We:

1. resolve or create the active web-chat ``Conversation`` for ``(workspace, job, primary identity, user)``,
2. persist the user message,
3. create a ``TaskExecution`` (event trigger) and enqueue :func:`core.tasks.task_execution.run_task_execution`
   so the agent replies via the unified ``send_message`` tool (which writes both the assistant
   ``Message`` and the real-time bridge event).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from core.models import CyberIdentity, JobAssignment, Message, WorkspaceMember
from core.services.auth import ApiKeyAuth, auth_service
from core.services.chat_clear_commands import CLEAR_CONTEXT_REPLY
from core.services.conversations import (
    append_user_message,
    archive_conversation,
    find_active_web_conversation,
    get_or_create_active_web_conversation,
)
from core.schemas.channel import WebChatChannel
from core.services.task_execution_runner import (
    WEB_CHAT_EVENT_SLUG,
    create_queued_event_task_execution,
    enqueue_task_execution,
)

router = Router(tags=["AgenticChat"])


class AgenticChatMessageRequest(Schema):
    message: str
    job_assignment_id: uuid.UUID


class AgenticChatMessageResponse(Schema):
    status: str
    conversation_id: str
    message_id: str
    job_assignment_id: str


class AgenticChatErrorResponse(Schema):
    error: str
    error_code: str


class AgenticChatHistoryMessage(Schema):
    id: uuid.UUID
    role: str
    content: str
    created: datetime
    attachments: list[dict[str, Any]]


class AgenticChatHistoryResponse(Schema):
    conversation_id: str | None
    messages: list[AgenticChatHistoryMessage]


class AgenticChatClearRequest(Schema):
    job_assignment_id: uuid.UUID


class AgenticChatClearResponse(Schema):
    status: str
    had_active_conversation: bool
    message: str


@dataclass(frozen=True)
class _WebChatJobContext:
    job: JobAssignment
    primary_identity: CyberIdentity


def _resolve_web_chat_job_context(
    *, user, job_assignment_id: uuid.UUID
) -> tuple[_WebChatJobContext | None, AgenticChatErrorResponse | None, int | None]:
    """Return ``(ctx, None, None)`` on success, or ``(None, error, http_status)`` on failure."""
    job = JobAssignment.objects.select_related("workspace", "identity").filter(id=job_assignment_id).first()
    if job is None:
        return (
            None,
            AgenticChatErrorResponse(
                error="Job assignment not found.", error_code="JOB_ASSIGNMENT_NOT_FOUND"
            ),
            404,
        )

    member = WorkspaceMember.objects.filter(
        user=user,
        workspace=job.workspace,
        status=WorkspaceMember.Status.ACTIVE,
    ).first()
    if member is None:
        raise HttpError(403, "You are not an active member of this workspace.")

    if not job.enabled:
        return (
            None,
            AgenticChatErrorResponse(
                error="This job assignment is disabled.", error_code="JOB_DISABLED"
            ),
            400,
        )

    identity = job.identity
    if identity is None:
        return (
            None,
            AgenticChatErrorResponse(
                error="This job has no cyber identity; assign one to use web chat.",
                error_code="JOB_HAS_NO_IDENTITY",
            ),
            400,
        )

    if not identity.is_active:
        return (
            None,
            AgenticChatErrorResponse(
                error="This cyber identity is inactive.", error_code="CYBER_IDENTITY_INACTIVE"
            ),
            400,
        )

    return (_WebChatJobContext(job=job, primary_identity=identity), None, None)


def _message_display_text(message: Message) -> str:
    text = (message.content_text or "").strip()
    if text:
        return text
    if message.content_structured is not None:
        return ""
    return ""


def _message_attachments(message: Message) -> list[dict[str, Any]]:
    structured = message.content_structured
    if not isinstance(structured, dict):
        return []
    attachments = structured.get("attachments")
    if not isinstance(attachments, list):
        return []
    return [a for a in attachments if isinstance(a, dict)]


@router.get("/health", response={200: dict}, auth=[ApiKeyAuth(), django_auth])
def health(request):
    return 200, {"status": "ok", "service": "agentic-chat"}


@router.get(
    "/history",
    response={
        200: AgenticChatHistoryResponse,
        400: AgenticChatErrorResponse,
        404: AgenticChatErrorResponse,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def get_conversation_history(request, job_assignment_id: uuid.UUID, limit: int = 200):
    """Return messages for the active web-chat thread for this job and the current user."""
    user = auth_service.get_user_from_request(request)
    ctx, err, status = _resolve_web_chat_job_context(user=user, job_assignment_id=job_assignment_id)
    if ctx is None:
        assert err is not None and status is not None
        return status, err

    conversation = find_active_web_conversation(
        workspace=ctx.job.workspace,
        cyber_identity=ctx.primary_identity,
        web_user_id=user.id,
        job_assignment_id=ctx.job.id,
    )
    if conversation is None:
        return 200, AgenticChatHistoryResponse(conversation_id=None, messages=[])

    capped = max(1, min(500, int(limit or 200)))
    rows = (
        Message.objects.filter(conversation=conversation)
        .order_by("created")[:capped]
        .iterator()
    )
    messages = [
        AgenticChatHistoryMessage(
            id=m.id,
            role=m.role,
            content=_message_display_text(m),
            created=m.created,
            attachments=_message_attachments(m),
        )
        for m in rows
    ]
    return 200, AgenticChatHistoryResponse(
        conversation_id=str(conversation.id),
        messages=messages,
    )


@router.post(
    "/conversation/clear",
    response={
        200: AgenticChatClearResponse,
        400: AgenticChatErrorResponse,
        404: AgenticChatErrorResponse,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def clear_conversation(request, data: AgenticChatClearRequest):
    """Archive the active web-chat thread so the next message starts fresh (no agent run)."""
    user = auth_service.get_user_from_request(request)
    ctx, err, status = _resolve_web_chat_job_context(
        user=user, job_assignment_id=data.job_assignment_id
    )
    if ctx is None:
        assert err is not None and status is not None
        return status, err

    convo = find_active_web_conversation(
        workspace=ctx.job.workspace,
        cyber_identity=ctx.primary_identity,
        web_user_id=user.id,
        job_assignment_id=ctx.job.id,
    )
    had = convo is not None
    if convo is not None:
        archive_conversation(convo)

    return 200, AgenticChatClearResponse(
        status="cleared",
        had_active_conversation=had,
        message=CLEAR_CONTEXT_REPLY,
    )


@router.post(
    "/messages",
    response={
        200: AgenticChatMessageResponse,
        400: AgenticChatErrorResponse,
        404: AgenticChatErrorResponse,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def send_message(request, data: AgenticChatMessageRequest):
    text = (data.message or "").strip()
    if not text:
        return 400, AgenticChatErrorResponse(
            error="message cannot be empty.", error_code="MESSAGE_REQUIRED"
        )

    user = auth_service.get_user_from_request(request)
    ctx, err, status = _resolve_web_chat_job_context(
        user=user, job_assignment_id=data.job_assignment_id
    )
    if ctx is None:
        assert err is not None and status is not None
        return status, err

    job = ctx.job
    identity = ctx.primary_identity

    conversation = get_or_create_active_web_conversation(
        workspace=job.workspace,
        cyber_identity=identity,
        web_user_id=user.id,
        job_assignment_id=job.id,
    )
    msg = append_user_message(conversation, content_text=text)

    channel = WebChatChannel(
        type="web_chat",
        user_id=user.id,
        cyber_identity_id=identity.id,
        job_assignment_id=job.id,
    )
    instructions = text if text else "Web chat inbound message (no text)."
    task_ex = create_queued_event_task_execution(
        job=job,
        task_instructions=instructions,
        channel=channel,
        event_slug=WEB_CHAT_EVENT_SLUG,
        conversation_id=conversation.id,
        triggering_message_id=msg.id,
    )
    enqueue_task_execution(task_ex.id)

    return 200, AgenticChatMessageResponse(
        status="processing",
        conversation_id=str(conversation.id),
        message_id=str(msg.id),
        job_assignment_id=str(job.id),
    )
