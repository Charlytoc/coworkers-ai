"""Resolve which catalog actionables apply to a workspace given its connected integration accounts."""

from __future__ import annotations

import uuid
from typing import Any

from ninja.errors import HttpError

from core.integrations.actionables import (
    ACTIONABLES,
    ARTIFACTS_CALL_CREATOR,
    SYSTEM_SEND_MESSAGE,
    TASKS_CREATE_RECURRING_JOB,
    TASKS_SCHEDULE_ONE_OFF,
)
from core.integrations.event_types import EVENT_TYPES
from core.integrations.integration_provider_registry import (
    ACTIONABLE_CATALOG_PROVIDER_TO_INTEGRATION,
    DM_PROVIDERS,
    WORKSPACE_CATALOG_ACTIONABLES,
    exclusive_inbound_event_slugs,
    is_direct_dm_slug,
    is_reply_dm_slug,
)
from core.models import CyberIdentity, IntegrationAccount, JobAssignment, Workspace
from core.schemas.job_assignment import (
    JobAssignmentConfig,
    JobAssignmentConfigAccount,
    JobAssignmentEventTrigger,
)


EXCLUSIVE_INBOUND_EVENTS = exclusive_inbound_event_slugs()


def append_default_event_triggers_if_empty(config: JobAssignmentConfig) -> None:
    """When ``triggers`` was omitted from the API payload, infer inbound listeners from send actions."""
    if config.triggers:
        return
    for d in DM_PROVIDERS:
        if any(a.actionable_slug == d.reply_dm_slug for a in config.actions):
            config.triggers.append(
                JobAssignmentEventTrigger(type="event", on=d.inbound_event_slug, filter={})
            )


def _inbound_listener_pairs(config: JobAssignmentConfig) -> set[tuple[str, uuid.UUID]]:
    """Pairs (event_slug, integration_account_id) this job would compete on for inbound dispatch."""
    event_slugs = {
        tr.on
        for tr in config.triggers
        if isinstance(tr, JobAssignmentEventTrigger) and tr.on in EXCLUSIVE_INBOUND_EVENTS
    }
    if not event_slugs:
        return set()
    out: set[tuple[str, uuid.UUID]] = set()
    for d in DM_PROVIDERS:
        if d.inbound_event_slug not in event_slugs:
            continue
        for a in config.actions:
            if a.actionable_slug == d.reply_dm_slug and a.integration_account_id is not None:
                out.add((d.inbound_event_slug, a.integration_account_id))
    return out


def assert_unique_inbound_event_listeners(
    *,
    workspace: Workspace,
    config: JobAssignmentConfig,
    exclude_job_assignment_id: uuid.UUID | None = None,
) -> None:
    """At most one **enabled** job per workspace may listen to a given inbound DM event per integration account."""
    mine = _inbound_listener_pairs(config)
    if not mine:
        return
    qs = JobAssignment.objects.filter(workspace=workspace, enabled=True)
    if exclude_job_assignment_id is not None:
        qs = qs.exclude(id=exclude_job_assignment_id)
    for other in qs.iterator():
        overlap = mine & _inbound_listener_pairs(other.get_config())
        if overlap:
            ev, acc = next(iter(overlap))
            raise HttpError(
                400,
                "Inbound listener conflict: another enabled job in this workspace ("
                f"{other.role_name!r}) already handles event {ev!r} for integration account {acc}. "
                "Remove this trigger, adjust the other job, or disable one of the jobs.",
            )


def _account_row(acc: IntegrationAccount) -> dict[str, Any]:
    return {
        "integration_account_id": str(acc.id),
        "provider": acc.provider,
        "display_name": acc.display_name or acc.external_account_id or str(acc.id),
        "status": acc.status,
    }


def list_actionable_catalog_for_workspace(workspace: Workspace) -> list[dict[str, Any]]:
    """UI-ready rows: one entry per (actionable, integration account) binding where applicable."""
    out: list[dict[str, Any]] = []
    accounts = list(
        IntegrationAccount.objects.filter(workspace=workspace).exclude(
            status=IntegrationAccount.Status.REVOKED,
        )
    )
    for acc in accounts:
        rows = WORKSPACE_CATALOG_ACTIONABLES.get(acc.provider)
        if not rows:
            continue
        for a in rows:
            out.append(
                {
                    "slug": a.slug,
                    "name": a.name,
                    "description": a.description,
                    "provider": a.provider,
                    "integration_account_id": str(acc.id),
                    "integration": _account_row(acc),
                }
            )
    for a in (
        ACTIONABLES[SYSTEM_SEND_MESSAGE.slug],
        ACTIONABLES[TASKS_SCHEDULE_ONE_OFF.slug],
        ACTIONABLES[TASKS_CREATE_RECURRING_JOB.slug],
        ACTIONABLES[ARTIFACTS_CALL_CREATOR.slug],
    ):
        out.append(
            {
                "slug": a.slug,
                "name": a.name,
                "description": a.description,
                "provider": a.provider,
                "integration_account_id": None,
                "integration": None,
            }
        )
    return out


def validate_job_assignment_config(
    *,
    workspace: Workspace,
    config: JobAssignmentConfig,
    exclude_job_assignment_id: uuid.UUID | None = None,
) -> JobAssignmentConfig:
    """Cross-check a parsed ``JobAssignmentConfig`` against DB state; enrich accounts.

    Mutates ``config`` in place and also returns it. Raises :class:`HttpError` on invalid references.
    """
    for i, acc in enumerate(config.accounts):
        stored = IntegrationAccount.objects.filter(id=acc.id, workspace=workspace).first()
        if stored is None:
            raise HttpError(400, f"config.accounts[{i}] is not in this workspace.")
        if stored.provider != acc.provider:
            raise HttpError(
                400,
                f"config.accounts[{i}] provider mismatch (stored={stored.provider!r}, sent={acc.provider!r}).",
            )

    if len(config.identities) == 0:
        raise HttpError(400, "At least one cyber identity is required (config.identities).")
    for i, ident in enumerate(config.identities):
        stored = CyberIdentity.objects.filter(id=ident.id, workspace=workspace).first()
        if stored is None:
            raise HttpError(400, f"config.identities[{i}] is not in this workspace.")
        if stored.type != ident.type:
            raise HttpError(
                400,
                f"config.identities[{i}] type mismatch (stored={stored.type!r}, sent={ident.type!r}).",
            )

    for i, tr in enumerate(config.triggers):
        if isinstance(tr, JobAssignmentEventTrigger) and tr.on not in EVENT_TYPES:
            raise HttpError(400, f"config.triggers[{i}] unknown event slug: {tr.on!r}.")

    seen_accounts = {acc.id for acc in config.accounts}
    for i, act in enumerate(config.actions):
        catalog = ACTIONABLES.get(act.actionable_slug)
        if catalog is None:
            raise HttpError(400, f"config.actions[{i}] unknown actionable slug: {act.actionable_slug!r}.")
        if catalog.provider == "system":
            if act.integration_account_id is not None:
                raise HttpError(
                    400,
                    f"Action {act.actionable_slug!r} is a system capability and must not have integration_account_id.",
                )
            continue
        expected = ACTIONABLE_CATALOG_PROVIDER_TO_INTEGRATION.get(catalog.provider)
        if expected is None:
            raise HttpError(
                400,
                f"Action {act.actionable_slug!r} has unsupported actionable provider {catalog.provider!r}.",
            )
        if act.integration_account_id is None:
            raise HttpError(400, f"Action {act.actionable_slug!r} requires integration_account_id.")
        acc = IntegrationAccount.objects.filter(
            id=act.integration_account_id, workspace=workspace
        ).first()
        if acc is None:
            raise HttpError(
                400,
                f"integration_account_id for action {act.actionable_slug!r} is not in this workspace.",
            )
        if acc.provider != expected:
            raise HttpError(
                400,
                f"Action {act.actionable_slug!r} requires a {expected.label} integration account.",
            )
        if acc.id not in seen_accounts:
            config.accounts.append(JobAssignmentConfigAccount(id=acc.id, provider=acc.provider))
            seen_accounts.add(acc.id)

    for i, act in enumerate(config.actions):
        slug = act.actionable_slug
        rec = act.direct_dm_recipients
        if rec and not is_direct_dm_slug(slug):
            raise HttpError(
                400,
                f"config.actions[{i}]: direct_dm_recipients is only allowed for telegram.send_direct_dm "
                f"or instagram.send_direct_dm (got {slug!r}).",
            )
        if is_reply_dm_slug(slug) and rec:
            raise HttpError(
                400,
                f"config.actions[{i}]: direct_dm_recipients must be empty for reply actions ({slug!r}).",
            )
        if is_direct_dm_slug(slug):
            if not rec:
                raise HttpError(
                    400,
                    f"config.actions[{i}]: {slug!r} requires at least one direct_dm_recipients entry.",
                )
            seen_tid: set[str] = set()
            for j, row in enumerate(rec):
                tid = (row.external_thread_id or "").strip()
                if not tid:
                    raise HttpError(
                        400,
                        f"config.actions[{i}].direct_dm_recipients[{j}]: external_thread_id is required.",
                    )
                if tid in seen_tid:
                    raise HttpError(
                        400,
                        f"config.actions[{i}]: duplicate external_thread_id in direct_dm_recipients.",
                    )
                seen_tid.add(tid)

    assert_unique_inbound_event_listeners(
        workspace=workspace,
        config=config,
        exclude_job_assignment_id=exclude_job_assignment_id,
    )
    return config
