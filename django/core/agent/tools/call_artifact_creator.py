"""Tool: delegate artifact creation to a child ``TaskExecution``."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError

from core.agent.base import AgentTool, AgentToolConfig
from core.integrations.actionables import (
    ARTIFACTS_CREATE_IMAGE,
    ARTIFACTS_CREATE_TEXT,
    INSTAGRAM_PUBLISH_EXTERNAL_RESOURCE,
)
from core.models import JobAssignment, TaskExecution
from core.schemas.agent_tools import CallArtifactCreatorArgs, SCHEDULE_ONE_OFF_MAX_MINUTES
from core.schemas.channel import Channel
from core.schemas.job_assignment import JobAssignmentAction
from core.schemas.task_execution import IdentityConfigSnapshot, TaskExecutionInputs

logger = logging.getLogger(__name__)


def make_call_artifact_creator_tool(
    *,
    job: JobAssignment,
    channel: Channel | None,
) -> AgentToolConfig:
    """Return a ``call_artifact_creator`` tool bound to the current job + channel."""

    tool = AgentTool(
        type="function",
        name="call_artifact_creator",
        description=(
            "Create a child artifact-creator task. Use this when the user asks to create durable "
            "content such as a note, caption, draft, image, post, or future media asset. The child "
            "task starts with text and image artifact tools enabled. If this parent job has Instagram "
            "publishing rights, the child will also receive `publish_external_resource`; use that path "
            "when the user asks to publish an Instagram post. After calling this, tell the user it may "
            "take a bit. When the child finishes (success or failure), this job will run again "
            "automatically so you can notify the user through the appropriate send tool."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "Short human-readable name for the artifact task.",
                },
                "instructions": {
                    "type": "string",
                    "minLength": 1,
                    "description": "What the child artifact creator should make and any context it needs.",
                },
                "in_minutes": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": SCHEDULE_ONE_OFF_MAX_MINUTES,
                    "default": 0,
                    "description": "How many minutes from now to run. Use 0 for now.",
                },
            },
            "required": ["name", "instructions"],
            "additionalProperties": False,
        },
    )

    def execute(name: str, instructions: str, in_minutes: int = 0) -> str:
        try:
            args = CallArtifactCreatorArgs(
                name=name,
                instructions=instructions,
                in_minutes=in_minutes,
            )
        except ValidationError as exc:
            return f"Error: {exc.errors()[0]['msg']}"

        cfg_model = job.get_config()
        identity_snapshot: IdentityConfigSnapshot | None = None
        if cfg_model.identities:
            first = cfg_model.identities[0]
            identity_snapshot = IdentityConfigSnapshot(identity=first.id, config=first.config)
        publish_actions = [
            action
            for action in cfg_model.actions
            if action.actionable_slug == INSTAGRAM_PUBLISH_EXTERNAL_RESOURCE.slug
        ]

        scheduled_to = None if args.in_minutes == 0 else timezone.now() + timedelta(minutes=args.in_minutes)
        inputs = TaskExecutionInputs(
            task_instructions=args.instructions,
            parent_job_assignment=job.id,
            identity_config=identity_snapshot,
            channel=channel,
            trigger={"type": "artifact_creator", "by_job_assignment": str(job.id)},
            actions=[
                JobAssignmentAction(
                    actionable_slug=ARTIFACTS_CREATE_TEXT.slug,
                    integration_account_id=None,
                ),
                JobAssignmentAction(
                    actionable_slug=ARTIFACTS_CREATE_IMAGE.slug,
                    integration_account_id=None,
                ),
                *publish_actions,
            ],
        )

        with transaction.atomic():
            task = TaskExecution(
                workspace=job.workspace,
                job_assignment=job,
                name=args.name,
                status=TaskExecution.Status.PENDING,
                requires_approval=False,
                scheduled_to=scheduled_to,
            )
            task.set_inputs(inputs)
            task.save()

        logger.info(
            "call_artifact_creator: created task=%s parent_job=%s in_minutes=%s",
            task.id,
            job.id,
            args.in_minutes,
        )
        if args.in_minutes == 0:
            from core.services.task_execution_runner import enqueue_task_execution

            TaskExecution.objects.filter(
                id=task.id,
                status=TaskExecution.Status.PENDING,
            ).update(status=TaskExecution.Status.QUEUED)
            enqueue_task_execution(task.id)
            return (
                f"Started artifact creator task {task.id}. When it finishes, this job will run again "
                "so you can notify the user."
            )
        return (
            f"Scheduled artifact creator task {task.id} to run at {scheduled_to.isoformat()} "
            f"(in {args.in_minutes} minutes). When it finishes, this job will run again so you can notify the user."
        )

    return AgentToolConfig(tool=tool, function=execute)
