"""Route inbound Instagram DMs: resolve Conversation, persist user Message, enqueue agent."""

from __future__ import annotations

import logging
from typing import Any

from core.integrations.event_types import INSTAGRAM_DM_MESSAGE
from core.models import IntegrationAccount
from core.schemas.integration_account import SenderApprovalStatus
from core.services.chat_clear_commands import CLEAR_CONTEXT_REPLY, is_clear_context_text
from core.services.integration_senders import merge_extractions, upsert_sender
from core.services.conversations import (
    archive_conversation,
    find_active_conversation,
)
from core.services.inbound_dm_agent_pipeline import enqueue_inbound_dm_task_execution
from core.services.instagram_service import (
    get_access_token,
    get_ig_user_id,
    instagram_dm_sender_handle_from_webhook_or_profile,
    instagram_fetch_participant_profile,
    instagram_send_message,
)
from core.services.job_task_processor_agent import JobTaskProcessorAgent

logger = logging.getLogger(__name__)


def process_instagram_dm(
    *,
    account: IntegrationAccount,
    messaging: dict[str, Any],
    sender_igsid: str,
) -> None:
    """Resolve conversation, persist the user message, enqueue the agent."""
    message = messaging.get("message") or {}
    text = (message.get("text") or "").strip()

    logger.info(
        "process_instagram_dm start integration_account_id=%s sender_igsid=%s text_len=%s mid=%s",
        account.id,
        sender_igsid,
        len(text),
        str(message.get("mid") or "")[:80],
    )

    token = get_access_token(account)
    profile = (
        instagram_fetch_participant_profile(
            account=account, access_token=token, participant_igsid=sender_igsid
        )
        if token
        else None
    )
    handle = instagram_dm_sender_handle_from_webhook_or_profile(messaging, profile)

    upsert_sender(
        account,
        sender_igsid,
        default_status=SenderApprovalStatus.NOT_REQUIRED,
        handle=handle,
    )

    if profile:
        merge_extractions(
            account,
            sender_igsid,
            {"instagram_user_profile": dict(profile)},
        )

    if is_clear_context_text(text):
        convo = find_active_conversation(account=account, external_thread_id=sender_igsid)
        if convo is not None:
            archive_conversation(convo)
        ig_user_id = get_ig_user_id(account)
        if token and ig_user_id:
            try:
                instagram_send_message(token, ig_user_id, sender_igsid, CLEAR_CONTEXT_REPLY)
            except Exception:
                logger.exception(
                    "process_instagram_dm clear_context send_failed account_id=%s sender=%s",
                    account.id,
                    sender_igsid,
                )
        else:
            logger.warning(
                "process_instagram_dm clear_context skip_send missing_token account_id=%s",
                account.id,
            )
        return

    job = JobTaskProcessorAgent.first_runnable_job_for_instagram_dm(account)
    if job is None:
        logger.warning(
            "process_instagram_dm no_runnable_job integration_account_id=%s workspace_id=%s",
            account.id,
            account.workspace_id,
        )
        return

    enqueued = enqueue_inbound_dm_task_execution(
        job=job,
        account=account,
        external_thread_id=sender_igsid,
        external_user_id=sender_igsid,
        text=text,
        event_slug=INSTAGRAM_DM_MESSAGE.slug,
        structured_message={"instagram_message": messaging},
        empty_text_instructions="Instagram inbound message (no text).",
    )
    if not enqueued:
        logger.warning(
            "process_instagram_dm enqueue_skipped job_id=%s integration_account_id=%s",
            job.id,
            account.id,
        )
        return

    logger.info(
        "process_instagram_dm enqueue_agent job_id=%s",
        job.id,
    )
