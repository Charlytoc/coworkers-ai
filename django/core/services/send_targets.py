"""Resolve validated outbound send targets for a job (Conversation-free core primitive)."""

from __future__ import annotations

import logging
import uuid
from typing import NamedTuple

from core.integrations.integration_provider_registry import (
    dm_provider_config,
    is_direct_dm_slug,
)
from core.models import Conversation, IntegrationAccount, JobAssignment
from core.schemas.job_assignment import JobAssignmentAction
from core.schemas.send_target import (
    ResolvedSendTarget,
    SendTargetProvider,
    SendTargetResolution,
)
from core.services.integration_senders import get_sender

logger = logging.getLogger(__name__)


class SendTargetSeed(NamedTuple):
    """Explicit (account, thread, role) for one possible recipient in this agent run."""

    integration_account: IntegrationAccount
    external_thread_id: str
    target_role: str
    target_kind: str


def resolve_send_target(
    *,
    job: JobAssignment,
    integration_account: IntegrationAccount,
    external_thread_id: str,
    required_action_slug: str,
    actions: list[JobAssignmentAction] | None = None,
) -> SendTargetResolution | None:
    """Return a validated send target if the job may send to this integration + thread.

    ``required_action_slug`` must be the catalog slug that authorizes this send
    (``*.reply_dm`` or ``*.send_direct_dm`` for the provider).
    """
    tid = (external_thread_id or "").strip()
    if not tid:
        return None

    active_actions = actions if actions is not None else job.get_config().actions
    provider = integration_account.provider
    cfg = dm_provider_config(provider)
    if cfg is None:
        return None

    if not any(
        a.actionable_slug == required_action_slug and a.integration_account_id == integration_account.id
        for a in active_actions
    ):
        return None

    sender = get_sender(integration_account, tid)
    if sender is None:
        return None

    if required_action_slug == cfg.reply_dm_slug:
        if not cfg.reply_sender_allowed(sender.approval_status):
            return None
    elif required_action_slug == cfg.direct_dm_slug:
        if not cfg.direct_sender_allowed(sender.approval_status):
            return None
    else:
        return None

    return SendTargetResolution(
        provider=cfg.send_target_provider,
        integration_account_id=integration_account.id,
        external_thread_id=tid,
    )


def _reply_seeds_from_conversation(
    conversation: Conversation | None,
) -> list[SendTargetSeed]:
    if (
        conversation is None
        or conversation.origin != Conversation.Origin.INTEGRATION
        or conversation.integration_account_id is None
    ):
        return []
    account = conversation.integration_account
    tid = (conversation.get_config().external_thread_id or "").strip()
    if not tid or account.provider not in (
        IntegrationAccount.Provider.TELEGRAM,
        IntegrationAccount.Provider.INSTAGRAM,
    ):
        return []
    return [
        SendTargetSeed(
            integration_account=account,
            external_thread_id=tid,
            target_role="This is the user you are interacting with right now.",
            target_kind="reply",
        )
    ]


def _direct_seeds_from_actions(
    *,
    workspace_id: int,
    actions: list[JobAssignmentAction],
) -> list[SendTargetSeed]:
    out: list[SendTargetSeed] = []
    for act in actions:
        if not is_direct_dm_slug(act.actionable_slug):
            continue
        if act.integration_account_id is None:
            continue
        account = IntegrationAccount.objects.filter(
            id=act.integration_account_id, workspace_id=workspace_id
        ).first()
        if account is None:
            continue
        for row in act.direct_dm_recipients:
            tid = (row.external_thread_id or "").strip()
            if not tid:
                continue
            label = (row.label or "").strip()
            role = f"Direct DM recipient: {label}" if label else "Direct DM recipient (configured thread)"
            out.append(
                SendTargetSeed(
                    integration_account=account,
                    external_thread_id=tid,
                    target_role=role,
                    target_kind="direct",
                )
            )
    return out


def collect_resolved_send_targets(
    *,
    job: JobAssignment,
    conversation: Conversation | None,
    actions: list[JobAssignmentAction] | None = None,
) -> list[ResolvedSendTarget]:
    """Build the indexed target list for this run from explicit seeds (not a full sender scan)."""
    active_actions = actions if actions is not None else job.get_config().actions
    if conversation is not None and conversation.origin == Conversation.Origin.WEB:
        web_user_id = conversation.get_config().web_user_id
        if web_user_id is not None:
            return [
                ResolvedSendTarget(
                    target_index=0,
                    target_role="This is the web chat user you are interacting with right now.",
                    provider=SendTargetProvider.WEB_CHAT,
                    web_user_id=web_user_id,
                    target_kind=None,
                )
            ]

    seeds: list[SendTargetSeed] = []
    seeds.extend(_reply_seeds_from_conversation(conversation))
    seen: set[tuple[uuid.UUID, str]] = {(s.integration_account.id, s.external_thread_id) for s in seeds}
    for s in _direct_seeds_from_actions(workspace_id=job.workspace_id, actions=active_actions):
        key = (s.integration_account.id, s.external_thread_id)
        if key in seen:
            continue
        seen.add(key)
        seeds.append(s)

    out: list[ResolvedSendTarget] = []
    for seed in seeds:
        cfg = dm_provider_config(seed.integration_account.provider)
        if cfg is None:
            continue
        slug = cfg.reply_dm_slug if seed.target_kind == "reply" else cfg.direct_dm_slug
        res = resolve_send_target(
            job=job,
            integration_account=seed.integration_account,
            external_thread_id=seed.external_thread_id,
            required_action_slug=slug,
            actions=active_actions,
        )
        if res is None:
            logger.info(
                "send_targets skip_seed job_id=%s account_id=%s thread_prefix=%s kind=%s",
                job.id,
                seed.integration_account.id,
                seed.external_thread_id[:24],
                seed.target_kind,
            )
            continue
        kind: str | None = seed.target_kind if seed.target_kind in ("reply", "direct") else None
        out.append(
            ResolvedSendTarget(
                target_index=len(out),
                target_role=seed.target_role,
                provider=res.provider,
                integration_account_id=res.integration_account_id,
                external_thread_id=res.external_thread_id,
                target_kind=kind,
            )
        )
    return out


def reindex_send_targets(targets: list[ResolvedSendTarget]) -> list[ResolvedSendTarget]:
    return [t.model_copy(update={"target_index": i}) for i, t in enumerate(targets)]
