"""Default ``JobAssignment`` provisioning — used during onboarding (e.g. first Telegram connect)."""

from __future__ import annotations

import logging

from django.db import transaction

from core.integrations.actionables import (
    INSTAGRAM_MANAGE_COMMENTS,
    INSTAGRAM_MEDIA_INSIGHTS,
    INSTAGRAM_PUBLISH_EXTERNAL_RESOURCE,
    INSTAGRAM_REPLY_DM,
    MEMORY_RECALL,
    MEMORY_REMEMBER,
    TASKS_CREATE_RECURRING_JOB,
    TASKS_SCHEDULE_ONE_OFF,
    TELEGRAM_REPLY_DM,
)
from core.integrations.event_types import INSTAGRAM_DM_MESSAGE, TELEGRAM_PRIVATE_MESSAGE
from core.models import CyberIdentity, IntegrationAccount, JobAssignment
from core.services.instagram_capabilities import account_has_capability
from core.schemas.job_assignment import (
    JobAssignmentAction,
    JobAssignmentConfig,
    JobAssignmentConfigAccount,
    JobAssignmentEventTrigger,
)

logger = logging.getLogger(__name__)


DEFAULT_TELEGRAM_ROLE_NAME = "Telegram Personal Assistant"
DEFAULT_TELEGRAM_DESCRIPTION = (
    "Default assistant that handles private Telegram messages for this workspace. "
    "Answers the user, schedules reminders, and can set up simple routines."
)
DEFAULT_TELEGRAM_INSTRUCTIONS = """\
You are a helpful, friendly personal assistant reachable via Telegram.

=== CRITICAL: HOW THE USER SEES YOUR WORDS ===
The ONLY way the user ever receives anything from you is by calling the `send_message` tool
(with the correct `target_index` from the system prompt for this run).
- Your plain textual output (the "final response" of this loop) is NEVER shown to the user. It is discarded.
- If you want to say ANYTHING to the user — an answer, a clarifying question, a confirmation, an apology,
  even a simple "ok" — you MUST emit it through `send_message`. No exceptions.
- Do not assume there is some other UI. Telegram is the only channel.

You may (and should, when useful) send MULTIPLE messages in a single turn:
- Call `send_message` once per logical message (greeting, answer, follow-up question, ...).
- Prefer several short, clearly-scoped messages over one giant wall of text.
- It is fine to call the tool, then call it again with more content before ending the turn.

After you have sent everything you need the user to read, THEN you can finish the turn (no tool call).
Finishing the turn without having called `send_message` at least once means the user hears nothing,
which is a bug. Never do that unless you truly have nothing to communicate (e.g. you only scheduled a task
and already confirmed it to the user in a previous `send_message` call in this same turn).

=== Style ===
- Always reply in the same language the user writes in.
- Be concise, warm, and conversational. Avoid corporate boilerplate.
- When the user asks a question, answer it directly. If something is ambiguous, ask one clarifying
  question (via `send_message`) before acting.

=== Tools ===
- `send_message`: Use this for EVERY user-facing sentence (with the correct `target_index`). Multiple calls per turn are allowed
  and encouraged when it improves clarity.
- `schedule_one_off_task`: Use when the user asks for a one-off reminder or action in the near future
  (e.g. "recuérdame en 20 minutos", "ping me tomorrow at 9am"). Write the `task_instructions` so a
  future agent can act without extra context. Pass `in_minutes` (1..43200). After scheduling, confirm
  it to the user with `send_message`.
- `create_recurring_job`: Use only when the user clearly wants a recurring routine
  (e.g. "todos los lunes a las 9", "every weekday morning"). Set a precise 5-field cron in UTC.
  The new job is created DISABLED and must be approved by a human — tell the user that explicitly
  via `send_message`.

Never expose internal ids, tokens, or schemas to the user. Never promise to do something you cannot do.
"""


DEFAULT_IDENTITY_DISPLAY_NAME = "Personal Assistant"


def _ensure_default_identity(*, workspace, user) -> CyberIdentity:
    """Pick a personal-assistant identity for the workspace, creating a default one if none exists."""
    existing = CyberIdentity.objects.filter(workspace=workspace, is_active=True).order_by(
        "display_name"
    )
    pa = existing.filter(type=CyberIdentity.Type.PERSONAL_ASSISTANT).first()
    if pa is not None:
        return pa
    any_identity = existing.first()
    if any_identity is not None:
        return any_identity

    identity = CyberIdentity(
        workspace=workspace,
        created_by=user if getattr(user, "pk", None) else None,
        type=CyberIdentity.Type.PERSONAL_ASSISTANT,
        display_name=DEFAULT_IDENTITY_DISPLAY_NAME,
        is_active=True,
        config={},
    )
    identity.save()
    logger.info(
        "job_assignment_defaults: created default personal assistant identity=%s workspace=%s",
        identity.id, workspace.id,
    )
    return identity


def build_telegram_default_job_config(
    *, account: IntegrationAccount, identity: CyberIdentity
) -> JobAssignmentConfig:
    return JobAssignmentConfig(
        accounts=[
            JobAssignmentConfigAccount(id=account.id, provider=account.provider),
        ],
        triggers=[
            JobAssignmentEventTrigger(
                type="event",
                on=TELEGRAM_PRIVATE_MESSAGE.slug,
                filter={},
            ),
        ],
        actions=[
            JobAssignmentAction(
                actionable_slug=TELEGRAM_REPLY_DM.slug,
                integration_account_id=account.id,
            ),
            JobAssignmentAction(
                actionable_slug=TASKS_SCHEDULE_ONE_OFF.slug,
                integration_account_id=None,
            ),
            JobAssignmentAction(
                actionable_slug=TASKS_CREATE_RECURRING_JOB.slug,
                integration_account_id=None,
            ),
            JobAssignmentAction(
                actionable_slug=MEMORY_REMEMBER.slug,
                integration_account_id=None,
            ),
            JobAssignmentAction(
                actionable_slug=MEMORY_RECALL.slug,
                integration_account_id=None,
            ),
        ],
    )


def build_instagram_default_job_config(
    *, account: IntegrationAccount, identity: CyberIdentity
) -> JobAssignmentConfig:
    caps = (account.config or {}).get("capabilities")
    caps = caps if isinstance(caps, list) else None

    actions = [
        JobAssignmentAction(
            actionable_slug=INSTAGRAM_REPLY_DM.slug,
            integration_account_id=account.id,
        ),
        JobAssignmentAction(
            actionable_slug=INSTAGRAM_PUBLISH_EXTERNAL_RESOURCE.slug,
            integration_account_id=account.id,
        ),
    ]
    # Include comment/insight tools only when the connection actually granted those scopes
    # (Facebook Login). Instagram-Login accounts won't have them, so we omit rather than wire
    # actions that would fail at runtime.
    if account_has_capability(caps, INSTAGRAM_MANAGE_COMMENTS.required_capability):
        actions.append(
            JobAssignmentAction(
                actionable_slug=INSTAGRAM_MANAGE_COMMENTS.slug,
                integration_account_id=account.id,
            )
        )
    if account_has_capability(caps, INSTAGRAM_MEDIA_INSIGHTS.required_capability):
        actions.append(
            JobAssignmentAction(
                actionable_slug=INSTAGRAM_MEDIA_INSIGHTS.slug,
                integration_account_id=account.id,
            )
        )
    actions.extend(
        [
            JobAssignmentAction(
                actionable_slug=TASKS_SCHEDULE_ONE_OFF.slug,
                integration_account_id=None,
            ),
            JobAssignmentAction(
                actionable_slug=TASKS_CREATE_RECURRING_JOB.slug,
                integration_account_id=None,
            ),
            JobAssignmentAction(
                actionable_slug=MEMORY_REMEMBER.slug,
                integration_account_id=None,
            ),
            JobAssignmentAction(
                actionable_slug=MEMORY_RECALL.slug,
                integration_account_id=None,
            ),
        ]
    )

    return JobAssignmentConfig(
        accounts=[
            JobAssignmentConfigAccount(id=account.id, provider=account.provider),
        ],
        triggers=[
            JobAssignmentEventTrigger(
                type="event",
                on=INSTAGRAM_DM_MESSAGE.slug,
                filter={},
            ),
        ],
        actions=actions,
    )


def create_default_dm_job_for_account(
    *,
    account: IntegrationAccount,
    identity: CyberIdentity,
    role_name: str,
    description: str,
    instructions: str,
    enabled: bool = True,
) -> JobAssignment:
    if account.provider == IntegrationAccount.Provider.TELEGRAM:
        cfg = build_telegram_default_job_config(account=account, identity=identity)
    elif account.provider == IntegrationAccount.Provider.INSTAGRAM:
        cfg = build_instagram_default_job_config(account=account, identity=identity)
    else:
        raise ValueError(f"unsupported provider for default DM job: {account.provider!r}")
    workspace = account.workspace
    job = JobAssignment(
        workspace=workspace,
        role_name=role_name[:200],
        description=description,
        instructions=instructions,
        enabled=enabled,
        identity=identity,
    )
    job.set_config(cfg)
    job.save()
    return job


def _has_existing_job_for_telegram_account(account: IntegrationAccount) -> bool:
    """True if any enabled job already targets this Telegram account with ``telegram.reply_dm``."""
    for job in JobAssignment.objects.filter(workspace=account.workspace).iterator():
        try:
            cfg = job.get_config()
        except Exception:
            continue
        for act in cfg.actions:
            if (
                act.actionable_slug == TELEGRAM_REPLY_DM.slug
                and act.integration_account_id == account.id
            ):
                return True
    return False


def ensure_default_job_assignment_for_telegram(
    *, account: IntegrationAccount, user
) -> JobAssignment | None:
    """Create a sensible default ``JobAssignment`` for a freshly-connected Telegram account.

    No-op if:
    - ``account`` is not a Telegram account.
    - A job already targets this account with ``telegram.reply_dm``.

    Returns the created job (or ``None`` when skipped).
    """
    if account.provider != IntegrationAccount.Provider.TELEGRAM:
        return None
    if _has_existing_job_for_telegram_account(account):
        return None

    workspace = account.workspace
    identity = _ensure_default_identity(workspace=workspace, user=user)

    with transaction.atomic():
        job = create_default_dm_job_for_account(
            account=account,
            identity=identity,
            role_name=DEFAULT_TELEGRAM_ROLE_NAME,
            description=DEFAULT_TELEGRAM_DESCRIPTION,
            instructions=DEFAULT_TELEGRAM_INSTRUCTIONS,
            enabled=True,
        )

    logger.info(
        "job_assignment_defaults: created default job=%s account=%s identity=%s workspace=%s",
        job.id, account.id, identity.id, workspace.id,
    )
    return job


DEFAULT_INSTAGRAM_ROLE_NAME = "Instagram DM Assistant"
DEFAULT_INSTAGRAM_DESCRIPTION = (
    "Default assistant that handles Instagram direct messages for this workspace. "
    "Answers users, handles inquiries, and can schedule follow-ups."
)
DEFAULT_INSTAGRAM_INSTRUCTIONS = """\
You are a helpful, friendly assistant reachable via Instagram Direct Messages.

=== CRITICAL: HOW THE USER SEES YOUR WORDS ===
The ONLY way the user ever receives anything from you is by calling the `send_message` tool
(with the correct `target_index` from the system prompt for this run).
- Your plain textual output (the "final response" of this loop) is NEVER shown to the user. It is discarded.
- If you want to say ANYTHING to the user — an answer, a clarifying question, a confirmation, an apology,
  even a simple "ok" — you MUST emit it through `send_message`. No exceptions.
- Do not assume there is some other UI. Instagram DMs is the only channel.

You may (and should, when useful) send MULTIPLE messages in a single turn:
- Call `send_message` once per logical message.
- Prefer several short, clearly-scoped messages over one giant wall of text.

After you have sent everything you need the user to read, THEN you can finish the turn (no tool call).
Finishing the turn without having called `send_message` at least once means the user hears nothing,
which is a bug. Never do that unless you truly have nothing to communicate.

=== Style ===
- Always reply in the same language the user writes in.
- Be concise, warm, and conversational. Avoid corporate boilerplate.
- When the user asks a question, answer it directly. If something is ambiguous, ask one clarifying
  question (via `send_message`) before acting.
- If the user sends /clear, /reset, or /clearcontext alone, the system archives the DM thread and
  replies with a short confirmation outside this agent loop; you will not see that message as input here.

=== Tools ===
- `send_message`: Use this for EVERY user-facing sentence (with the correct `target_index`).
- `schedule_one_off_task`: Use when the user asks for a one-off reminder or action in the future.
- `create_recurring_job`: Use only when the user clearly wants a recurring routine.

Never expose internal ids, tokens, or schemas to the user. Never promise to do something you cannot do.
"""


def _has_existing_job_for_instagram_account(account: IntegrationAccount) -> bool:
    for job in JobAssignment.objects.filter(workspace=account.workspace).iterator():
        try:
            cfg = job.get_config()
        except Exception:
            continue
        for act in cfg.actions:
            if (
                act.actionable_slug == INSTAGRAM_REPLY_DM.slug
                and act.integration_account_id == account.id
            ):
                return True
    return False


def ensure_default_job_assignment_for_instagram(
    *, account: IntegrationAccount, user
) -> JobAssignment | None:
    """Create a sensible default ``JobAssignment`` for a freshly-connected Instagram account.

    No-op if:
    - ``account`` is not an Instagram account.
    - A job already targets this account with ``instagram.reply_dm``.
    """
    if account.provider != IntegrationAccount.Provider.INSTAGRAM:
        logger.info(
            "ensure_default_job_assignment_for_instagram skip wrong_provider account_id=%s provider=%s",
            account.id,
            account.provider,
        )
        return None
    if _has_existing_job_for_instagram_account(account):
        logger.info(
            "ensure_default_job_assignment_for_instagram skip job_already_exists account_id=%s workspace_id=%s",
            account.id,
            account.workspace_id,
        )
        return None

    workspace = account.workspace
    identity = _ensure_default_identity(workspace=workspace, user=user)

    with transaction.atomic():
        job = create_default_dm_job_for_account(
            account=account,
            identity=identity,
            role_name=DEFAULT_INSTAGRAM_ROLE_NAME,
            description=DEFAULT_INSTAGRAM_DESCRIPTION,
            instructions=DEFAULT_INSTAGRAM_INSTRUCTIONS,
            enabled=True,
        )

    logger.info(
        "job_assignment_defaults: created default instagram job=%s account=%s identity=%s workspace=%s",
        job.id, account.id, identity.id, workspace.id,
    )
    return job
