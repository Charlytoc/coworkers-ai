"""Bootstrap a freshly created workspace with a default identity and job assignment.

Called during onboarding and whenever a new workspace is created. Gives users
something to work with immediately — no integration required.
"""

from __future__ import annotations

import logging

from core.integrations.actionables import (
    ARTIFACTS_CALL_CREATOR,
    SYSTEM_SEND_MESSAGE,
    TASKS_CREATE_RECURRING_JOB,
    TASKS_SCHEDULE_ONE_OFF,
)
from core.models import CyberIdentity, JobAssignment, Workspace
from core.models.user import User
from core.schemas.job_assignment import JobAssignmentAction, JobAssignmentConfig

logger = logging.getLogger(__name__)

_DEFAULT_IDENTITY_NAME = "Personal Assistant"

_DEFAULT_JOB_ROLE = "Personal Assistant"
_DEFAULT_JOB_DESCRIPTION = (
    "Your default AI assistant. Ask it anything, have it draft content, "
    "create images, or schedule follow-up tasks."
)
_DEFAULT_JOB_INSTRUCTIONS = (
    "You are a helpful personal assistant. Answer questions clearly and concisely. "
    "When the user asks you to create content (text, images, captions, drafts), use "
    "the artifact tools. When the user asks you to remind them of something or do a "
    "task at a later time, use the scheduling tools. Always reply through send_message."
)


def bootstrap_workspace(*, workspace: Workspace, created_by: User) -> None:
    """Create a starter CyberIdentity and JobAssignment for a new workspace.

    Idempotent: skips creation if either already exists.
    """
    if CyberIdentity.objects.filter(workspace=workspace).exists():
        logger.info("bootstrap_workspace skip identity_exists workspace=%s", workspace.id)
        return

    identity = CyberIdentity.objects.create(
        workspace=workspace,
        created_by=created_by,
        type=CyberIdentity.Type.PERSONAL_ASSISTANT,
        display_name=_DEFAULT_IDENTITY_NAME,
        is_active=True,
        config={},
    )
    logger.info("bootstrap_workspace created identity=%s workspace=%s", identity.id, workspace.id)

    cfg = JobAssignmentConfig(
        accounts=[],
        triggers=[],
        actions=[
            JobAssignmentAction(actionable_slug=SYSTEM_SEND_MESSAGE.slug, integration_account_id=None),
            JobAssignmentAction(actionable_slug=ARTIFACTS_CALL_CREATOR.slug, integration_account_id=None),
            JobAssignmentAction(actionable_slug=TASKS_SCHEDULE_ONE_OFF.slug, integration_account_id=None),
            JobAssignmentAction(actionable_slug=TASKS_CREATE_RECURRING_JOB.slug, integration_account_id=None),
        ],
    )
    job = JobAssignment(
        workspace=workspace,
        identity=identity,
        role_name=_DEFAULT_JOB_ROLE,
        description=_DEFAULT_JOB_DESCRIPTION,
        instructions=_DEFAULT_JOB_INSTRUCTIONS,
        enabled=True,
    )
    job.set_config(cfg)
    job.save()
    logger.info("bootstrap_workspace created job=%s workspace=%s", job.id, workspace.id)
