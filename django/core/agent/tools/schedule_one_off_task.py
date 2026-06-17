"""Tool: let the currently-running agent schedule a one-off ``TaskExecution``."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError

from core.agent.base import AgentTool, AgentToolConfig
from core.models import JobAssignment, TaskExecution
from core.schemas.agent_tools import SCHEDULE_ONE_OFF_MAX_MINUTES, ScheduleOneOffTaskArgs
from core.schemas.channel import Channel
from core.schemas.task_execution import IdentityConfigSnapshot, TaskExecutionInputs

logger = logging.getLogger(__name__)


def make_schedule_one_off_task_tool(
    *,
    job: JobAssignment,
    channel: Channel | None,
) -> AgentToolConfig:
    """Return a ``schedule_one_off_task`` tool bound to the current ``JobAssignment`` + channel."""

    tool = AgentTool(
        type="function",
        name="schedule_one_off_task",
        description=(
            "Schedule a one-off future task (e.g. reminders). Provide plain-text instructions "
            "for the future agent and the offset in minutes from now. "
            f"Offset must be 1..{SCHEDULE_ONE_OFF_MAX_MINUTES} minutes (up to 30 days). "
            "The task will inherit the same channel (e.g. Telegram chat) as the current job."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task_instructions": {
                    "type": "string",
                    "description": "What the future agent must do when this task fires. Include any context it will need.",
                },
                "in_minutes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": SCHEDULE_ONE_OFF_MAX_MINUTES,
                    "description": "How many minutes from now to run the task.",
                },
            },
            "required": ["task_instructions", "in_minutes"],
            "additionalProperties": False,
        },
    )

    def execute(task_instructions: str, in_minutes: int) -> str:
        try:
            args = ScheduleOneOffTaskArgs(
                task_instructions=task_instructions,
                in_minutes=in_minutes,
            )
        except ValidationError as exc:
            return f"Error: {exc.errors()[0]['msg']}"

        identity_snapshot: IdentityConfigSnapshot | None = None
        if job.identity_id is not None:
            identity = job.identity
            identity_snapshot = IdentityConfigSnapshot(identity=identity.id, config=identity.config or {})

        scheduled_to = timezone.now() + timedelta(minutes=args.in_minutes)
        inputs = TaskExecutionInputs(
            task_instructions=args.task_instructions,
            parent_job_assignment=job.id,
            identity_config=identity_snapshot,
            channel=channel,
            trigger={"type": "agent_scheduled", "by_job_assignment": str(job.id)},
        )

        with transaction.atomic():
            task = TaskExecution(
                workspace=job.workspace,
                job_assignment=job,
                status=TaskExecution.Status.PENDING,
                requires_approval=False,
                scheduled_to=scheduled_to,
            )
            task.set_inputs(inputs)
            task.save()

        logger.info(
            "schedule_one_off_task: created task=%s job=%s in_minutes=%s",
            task.id, job.id, args.in_minutes,
        )
        return (
            f"Scheduled one-off task {task.id} to run at {scheduled_to.isoformat()} "
            f"(in {args.in_minutes} minutes)."
        )

    return AgentToolConfig(tool=tool, function=execute)
