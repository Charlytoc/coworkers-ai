"""Read/write ``IntegrationAccount.config[INTEGRATION_ONBOARDING_CONFIG_KEY]`` for connect flows."""

from __future__ import annotations

import logging
from typing import Any

from core.models import CyberIdentity, IntegrationAccount
from core.schemas.integration_account import (
    INTEGRATION_ONBOARDING_CONFIG_KEY,
    IntegrationAccountOnboarding,
)

logger = logging.getLogger(__name__)


def parse_onboarding_from_config(raw: dict[str, Any] | None) -> IntegrationAccountOnboarding | None:
    blob = (raw or {}).get(INTEGRATION_ONBOARDING_CONFIG_KEY)
    if blob is None:
        return None
    if not isinstance(blob, dict):
        return None
    try:
        return IntegrationAccountOnboarding.model_validate(blob)
    except Exception:
        logger.warning("integration_onboarding invalid payload", exc_info=True)
        return None


def merge_onboarding_into_config(
    raw: dict[str, Any] | None,
    onboarding: IntegrationAccountOnboarding,
) -> dict[str, Any]:
    cfg = dict(raw or {})
    cfg[INTEGRATION_ONBOARDING_CONFIG_KEY] = onboarding.model_dump(mode="json")
    return cfg


def pop_onboarding_from_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    cfg = dict(raw or {})
    cfg.pop(INTEGRATION_ONBOARDING_CONFIG_KEY, None)
    return cfg


def require_cyber_identity_in_workspace(
    *,
    workspace_id: int,
    cyber_identity_id,
) -> CyberIdentity:
    row = CyberIdentity.objects.filter(
        id=cyber_identity_id,
        workspace_id=workspace_id,
        is_active=True,
    ).first()
    if row is None:
        raise ValueError("cyber_identity_id is not an active identity in this workspace.")
    return row


def has_default_dm_job_for_integration_account(account: IntegrationAccount) -> bool:
    from core.integrations.actionables import INSTAGRAM_REPLY_DM, TELEGRAM_REPLY_DM
    from core.models import JobAssignment

    slug = (
        TELEGRAM_REPLY_DM.slug
        if account.provider == IntegrationAccount.Provider.TELEGRAM
        else INSTAGRAM_REPLY_DM.slug
        if account.provider == IntegrationAccount.Provider.INSTAGRAM
        else None
    )
    if slug is None:
        return False
    for job in JobAssignment.objects.filter(workspace=account.workspace).iterator():
        try:
            cfg = job.get_config()
        except Exception:
            continue
        for act in cfg.actions:
            if act.actionable_slug == slug and act.integration_account_id == account.id:
                return True
    return False
