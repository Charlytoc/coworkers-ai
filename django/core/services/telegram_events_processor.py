"""Route approved inbound Telegram traffic: resolve Conversation, persist user Message, enqueue agent."""

from __future__ import annotations

from typing import Any

from core.integrations.event_types import TELEGRAM_PRIVATE_MESSAGE
from core.models import IntegrationAccount, JobAssignment
from core.services.chat_clear_commands import CLEAR_CONTEXT_REPLY, is_clear_context_text
from core.services.conversations import (
    archive_conversation,
    find_active_conversation,
)
from core.schemas.integration_account import SenderApprovalStatus
from core.services.inbound_dm_agent_pipeline import enqueue_inbound_dm_task_execution
from core.services.integration_senders import upsert_sender
from core.services.job_task_processor_agent import JobTaskProcessorAgent
from core.services.telegram_bot import (
    get_bot_token,
    telegram_send_message,
    telegram_sender_handle_from_message,
)

NO_TASKS_REPLY = (
    "This bot has any defined tasks configured, please define something to "
    "start using your bot as an expert."
)


def _workspace_has_configured_jobs(account: IntegrationAccount) -> bool:
    """True when the workspace has at least one enabled job with identities and actions (may not match this bot)."""
    for job in JobAssignment.objects.filter(workspace=account.workspace, enabled=True).iterator():
        cfg_model = job.get_config()
        if cfg_model.actions and job.identity_id is not None:
            return True
    return False


def _is_clear_context_command(message: dict[str, Any]) -> bool:
    text = str(message.get("text") or message.get("caption") or "").strip()
    return is_clear_context_text(text)


def _external_user_id(message: dict[str, Any]) -> str | None:
    from_user = message.get("from") or {}
    uid = from_user.get("id")
    if uid is None:
        return None
    return str(uid)


def process_approved_message(account: IntegrationAccount, message: dict[str, Any]) -> None:
    """Resolve the conversation, persist the user message, enqueue the agent (or fall back)."""
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if chat_id is None:
        return
    external_thread_id = str(chat_id)

    upsert_sender(
        account,
        external_thread_id,
        default_status=SenderApprovalStatus.APPROVED,
        handle=telegram_sender_handle_from_message(message),
    )

    if _is_clear_context_command(message):
        convo = find_active_conversation(
            account=account, external_thread_id=external_thread_id
        )
        if convo is not None:
            archive_conversation(convo)
        bot_token = get_bot_token(account)
        if bot_token:
            telegram_send_message(bot_token, chat_id, CLEAR_CONTEXT_REPLY)
        return

    job = JobTaskProcessorAgent.first_runnable_job_for_telegram_private_message(account)
    if job is None:
        if _workspace_has_configured_jobs(account):
            return
        bot_token = get_bot_token(account)
        if not bot_token:
            return
        telegram_send_message(bot_token, chat_id, NO_TASKS_REPLY)
        return

    text = (message.get("text") or message.get("caption") or "").strip()
    enqueue_inbound_dm_task_execution(
        job=job,
        account=account,
        external_thread_id=external_thread_id,
        external_user_id=_external_user_id(message) or external_thread_id,
        text=text,
        event_slug=TELEGRAM_PRIVATE_MESSAGE.slug,
        structured_message={"telegram_message": message},
        empty_text_instructions="Telegram inbound message (no text).",
    )
