"""Tool: let the currently-running agent create a recurring ``JobAssignment`` (cron)."""

from __future__ import annotations

import logging

from django.db import transaction
from pydantic import ValidationError

from core.agent.base import AgentTool, AgentToolConfig
from core.models import JobAssignment
from core.schemas.agent_tools import CreateRecurringJobArgs
from core.schemas.channel import Channel
from core.schemas.job_assignment import (
    JobAssignmentConfig,
    JobAssignmentCronTrigger,
)

logger = logging.getLogger(__name__)


def _validate_cron(expr: str) -> str | None:
    """Return an error message if ``expr`` is not a valid 5-field UNIX cron, else ``None``."""
    try:
        from croniter import croniter
    except ImportError:
        return "Cron validation unavailable (croniter missing on server)."

    if not croniter.is_valid(expr):
        return "Invalid cron expression (expected 5 UNIX cron fields)."
    if expr.strip() == "* * * * *":
        return "Per-minute cron is not allowed."
    return None


def make_create_recurring_job_tool(
    *,
    job: JobAssignment,
    channel: Channel | None,
) -> AgentToolConfig:
    """Return a ``create_recurring_job`` tool bound to the current ``JobAssignment`` + channel."""

    tool = AgentTool(
        type="function",
        name="create_recurring_job",
        description=(
            "Create a new recurring job (routine) that fires on a cron schedule, e.g. "
            "'every Mon/Wed/Fri at 12:00'. The new job inherits the current job's accounts, "
            "identities and actions, and its cron trigger is the provided UNIX expression (UTC). "
            "The new job starts DISABLED and must be approved by a human from the UI before it runs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "role_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "Short role name for the routine, e.g. 'Gym reminder M-W-F'.",
                },
                "instructions": {
                    "type": "string",
                    "minLength": 1,
                    "description": "What the routine must do every time it fires.",
                },
                "cron": {
                    "type": "string",
                    "description": "5-field UNIX cron expression in UTC. Example: '0 12 * * 1,3,5'.",
                },
                "description": {
                    "type": "string",
                    "default": "",
                    "description": "Optional human-readable description.",
                },
            },
            "required": ["role_name", "instructions", "cron"],
            "additionalProperties": False,
        },
    )

    def execute(
        role_name: str,
        instructions: str,
        cron: str,
        description: str = "",
    ) -> str:
        try:
            args = CreateRecurringJobArgs(
                role_name=role_name,
                instructions=instructions,
                cron=cron,
                description=description,
            )
        except ValidationError as exc:
            return f"Error: {exc.errors()[0]['msg']}"

        cron_err = _validate_cron(args.cron)
        if cron_err is not None:
            return f"Error: {cron_err}"

        parent_cfg = job.get_config()
        inherited_channels: list[Channel] = list(parent_cfg.channels)
        if channel is not None and not any(
            getattr(c, "type", None) == channel.type
            and getattr(c, "integration_account_id", None) == channel.integration_account_id
            and getattr(c, "chat_id", None) == channel.chat_id
            for c in inherited_channels
        ):
            inherited_channels.append(channel)

        child_cfg = JobAssignmentConfig(
            accounts=list(parent_cfg.accounts),
            triggers=[JobAssignmentCronTrigger(type="cron", on=args.cron, filter={})],
            actions=list(parent_cfg.actions),
            channels=inherited_channels,
            approval_policy=parent_cfg.approval_policy,
            output_schema=parent_cfg.output_schema,
        )

        with transaction.atomic():
            child = JobAssignment(
                workspace=job.workspace,
                role_name=args.role_name,
                description=args.description,
                instructions=args.instructions,
                enabled=False,
                parent_job_assignment=job,
                identity=job.identity,
            )
            child.set_config(child_cfg)
            child.save()

        logger.info(
            "create_recurring_job: created job=%s parent=%s cron=%r",
            child.id, job.id, args.cron,
        )
        return (
            f"Created recurring job {child.id} ('{args.role_name}') with cron {args.cron!r}. "
            "It is DISABLED and awaiting human approval from the UI."
        )

    return AgentToolConfig(tool=tool, function=execute)
