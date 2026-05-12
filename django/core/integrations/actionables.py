"""Catalogue of actionables (agent capabilities). Referenced by slug from ``JobAssignment.config['actions']``.

Handlers/input schemas are intentionally omitted for now: this is just the static catalogue
so the rest of the system can validate slugs and expose them in the UI. Runtime wiring
lands together with the task runner.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Actionable:
    slug: str
    provider: str
    name: str
    description: str


TELEGRAM_REPLY_DM = Actionable(
    slug="telegram.reply_dm",
    provider="telegram",
    name="Reply to Telegram DM",
    description=(
        "Send a text reply in the active Telegram private chat thread for this run "
        "(same thread as the inbound message or the conversation bound to this task)."
    ),
)

INSTAGRAM_REPLY_DM = Actionable(
    slug="instagram.reply_dm",
    provider="instagram",
    name="Reply to Instagram DM",
    description=(
        "Send a text reply in the active Instagram DM thread for this run "
        "(same thread as the inbound message or the conversation bound to this task)."
    ),
)

TELEGRAM_SEND_DIRECT_DM = Actionable(
    slug="telegram.send_direct_dm",
    provider="telegram",
    name="Send Telegram DM (proactive)",
    description=(
        "Send a Telegram message to one of the thread ids listed on this action's "
        "`direct_dm_recipients`. Bots can only message users who have started a chat with the bot; "
        "each recipient must pass sender approval rules."
    ),
)

INSTAGRAM_SEND_DIRECT_DM = Actionable(
    slug="instagram.send_direct_dm",
    provider="instagram",
    name="Send Instagram DM (proactive)",
    description=(
        "Send an Instagram DM to one of the conversation thread ids listed on this action's "
        "`direct_dm_recipients`. Instagram messaging windows and approval rules still apply."
    ),
)

INSTAGRAM_PUBLISH_EXTERNAL_RESOURCE = Actionable(
    slug="instagram.publish_external_resource",
    provider="instagram",
    name="Publish Instagram post",
    description="Publish a generated artifact as an Instagram feed post and save the provider resource as an artifact.",
)


TASKS_SCHEDULE_ONE_OFF = Actionable(
    slug="tasks.schedule_one_off",
    provider="system",
    name="Schedule a one-off task",
    description=(
        "Let the agent schedule a future one-off task (e.g. reminders). "
        "Runs once at the specified offset and inherits the current job's channel and capabilities."
    ),
)

TASKS_CREATE_RECURRING_JOB = Actionable(
    slug="tasks.create_recurring_job",
    provider="system",
    name="Create a recurring job (cron)",
    description=(
        "Let the agent create a new JobAssignment that fires on a cron schedule "
        "(e.g. 'every Mon/Wed/Fri at 12:00'), inheriting accounts, identities and actions from the parent job."
    ),
)


SYSTEM_SEND_MESSAGE = Actionable(
    slug="system.send_message",
    provider="system",
    name="Send message",
    description=(
        "Deliver a message to the user via a system-managed channel such as in-app web chat. "
        "The destination is already bound; the agent only supplies the body."
    ),
)


ARTIFACTS_CALL_CREATOR = Actionable(
    slug="artifacts.call_creator",
    provider="system",
    name="Call artifact creator",
    description="Delegate artifact creation to a child task execution with a focused toolset.",
)

ARTIFACTS_CREATE_TEXT = Actionable(
    slug="artifacts.create_text",
    provider="system",
    name="Create text artifact",
    description="Persist a text artifact on the current task execution.",
)

ARTIFACTS_CREATE_IMAGE = Actionable(
    slug="artifacts.create_image",
    provider="system",
    name="Create image artifact",
    description="Generate an image with OpenAI and persist it as a media-backed artifact.",
)


ACTIONABLES: dict[str, Actionable] = {
    a.slug: a
    for a in (
        TELEGRAM_REPLY_DM,
        INSTAGRAM_REPLY_DM,
        TELEGRAM_SEND_DIRECT_DM,
        INSTAGRAM_SEND_DIRECT_DM,
        INSTAGRAM_PUBLISH_EXTERNAL_RESOURCE,
        TASKS_SCHEDULE_ONE_OFF,
        TASKS_CREATE_RECURRING_JOB,
        SYSTEM_SEND_MESSAGE,
        ARTIFACTS_CALL_CREATOR,
        ARTIFACTS_CREATE_TEXT,
        ARTIFACTS_CREATE_IMAGE,
    )
}


def get_actionable(slug: str) -> Actionable | None:
    return ACTIONABLES.get(slug)
