"""LLM-backed job copy (role name, description, instructions) for integration onboarding."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from django.conf import settings

from core.models import CyberIdentity, IntegrationAccount
from core.schemas.integration_account import IntegrationAccountOnboarding, LlmDefaultJobCopy
from core.services.job_assignment_defaults import (
    DEFAULT_INSTAGRAM_DESCRIPTION,
    DEFAULT_INSTAGRAM_INSTRUCTIONS,
    DEFAULT_INSTAGRAM_ROLE_NAME,
    DEFAULT_TELEGRAM_DESCRIPTION,
    DEFAULT_TELEGRAM_INSTRUCTIONS,
    DEFAULT_TELEGRAM_ROLE_NAME,
)
from core.services.openai_service import OpenAIService

logger = logging.getLogger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def _response_assistant_text(resp: Any) -> str:
    if resp is None:
        return ""
    out = getattr(resp, "output", None) or []
    for item in out:
        if getattr(item, "type", None) == "message" and getattr(item, "role", None) == "assistant":
            for part in getattr(item, "content", None) or []:
                t = getattr(part, "text", None)
                if t:
                    return str(t).strip()
    return ""


def generate_default_job_copy(
    *,
    account: IntegrationAccount,
    identity: CyberIdentity,
    onboarding: IntegrationAccountOnboarding,
) -> LlmDefaultJobCopy | None:
    api_key = (getattr(settings, "OPENAI_API_KEY", None) or "").strip()
    if not api_key:
        logger.warning("integration_job_copy_llm: OPENAI_API_KEY unset, using fallback copy")
        return None

    channel = (
        "Telegram private DMs (bot replies in the active thread; user-visible text only via send_message tool)"
        if account.provider == IntegrationAccount.Provider.TELEGRAM
        else "Instagram Direct Messages (user-visible text only via send_message tool)"
        if account.provider == IntegrationAccount.Provider.INSTAGRAM
        else str(account.provider)
    )

    system = (
        "You write configuration copy for an AI workspace job. Output must be a single JSON object only, "
        "no markdown fences, no commentary. Keys: role_name (string, <=200 chars), description (string, <=2000 chars), "
        "instructions (string, markdown-friendly, <=32000 chars).\n"
        "The job already has the correct tools and triggers in code; your instructions must tell the agent how to "
        "behave for THIS workspace and MUST include: (1) always use the send_message tool with the correct "
        "target_index for anything the end user must read; plain assistant text is not shown on the channel; "
        "(2) match the user's language; (3) never expose internal ids or tokens.\n"
        "Ground the persona in the chosen cyber identity display name and type.\n"
        "Align tone and priorities with the user's stated use case."
    )

    user_payload = {
        "integration_display_name": account.display_name or account.external_account_id,
        "integration_provider": account.provider,
        "channel": channel,
        "cyber_identity_display_name": identity.display_name,
        "cyber_identity_type": identity.type,
        "user_use_case": onboarding.use_case,
    }

    user_msg = (
        "Produce the JSON object now.\n\nContext (JSON):\n"
        + json.dumps(user_payload, ensure_ascii=False, indent=2)
    )

    try:
        svc = OpenAIService(api_key)
        resp = svc.create_response(
            input_data=user_msg,
            tools=None,
            model="gpt-5.4-mini",
            instructions=system,
            store=False,
            previous_response_id=None,
        )
        raw = _response_assistant_text(resp)
        if not raw:
            logger.warning("integration_job_copy_llm: empty model output")
            return None
        m = _JSON_OBJECT_RE.search(raw)
        if not m:
            logger.warning("integration_job_copy_llm: no JSON object in output")
            return None
        data = json.loads(m.group(0))
        return LlmDefaultJobCopy.model_validate(data)
    except Exception:
        logger.exception("integration_job_copy_llm: generation failed")
        return None


def fallback_copy_for_provider(account: IntegrationAccount) -> tuple[str, str, str]:
    if account.provider == IntegrationAccount.Provider.TELEGRAM:
        return DEFAULT_TELEGRAM_ROLE_NAME, DEFAULT_TELEGRAM_DESCRIPTION, DEFAULT_TELEGRAM_INSTRUCTIONS
    if account.provider == IntegrationAccount.Provider.INSTAGRAM:
        return DEFAULT_INSTAGRAM_ROLE_NAME, DEFAULT_INSTAGRAM_DESCRIPTION, DEFAULT_INSTAGRAM_INSTRUCTIONS
    return (
        "Integration assistant",
        "Handles messages for this connected account.",
        DEFAULT_TELEGRAM_INSTRUCTIONS,
    )
