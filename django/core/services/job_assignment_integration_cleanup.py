"""Keep ``JobAssignment`` rows consistent when an ``IntegrationAccount`` is removed."""

from __future__ import annotations

import logging
import uuid

from django.db import transaction

from core.models import JobAssignment
from core.schemas.channel import Channel, InstagramDmChannel, TelegramPrivateChannel
from core.schemas.job_assignment import JobAssignmentAction, JobAssignmentConfig

logger = logging.getLogger(__name__)


def _job_references_integration_account(cfg: JobAssignmentConfig, account_id: uuid.UUID) -> bool:
    if any(a.id == account_id for a in cfg.accounts):
        return True
    if any(a.integration_account_id == account_id for a in cfg.actions):
        return True
    for ch in cfg.channels:
        if isinstance(ch, (TelegramPrivateChannel, InstagramDmChannel)) and ch.integration_account_id == account_id:
            return True
    return False


def _sole_integration_account_in_accounts(cfg: JobAssignmentConfig, account_id: uuid.UUID) -> bool:
    return len(cfg.accounts) == 1 and cfg.accounts[0].id == account_id


def _strip_integration_account(cfg: JobAssignmentConfig, account_id: uuid.UUID) -> JobAssignmentConfig:
    new_accounts = [a for a in cfg.accounts if a.id != account_id]
    new_actions = [
        a.model_copy(
            update={
                "integration_account_id": None
                if a.integration_account_id == account_id
                else a.integration_account_id
            }
        )
        for a in cfg.actions
    ]
    new_channels: list[Channel] = []
    for ch in cfg.channels:
        if isinstance(ch, (TelegramPrivateChannel, InstagramDmChannel)) and ch.integration_account_id == account_id:
            continue
        new_channels.append(ch)
    return cfg.model_copy(update={"accounts": new_accounts, "actions": new_actions, "channels": new_channels})


def cleanup_job_assignments_for_deleted_integration_account(
    *,
    workspace_id: int,
    integration_account_id: uuid.UUID,
) -> None:
    """Drop or rewrite job configs that pointed at ``integration_account_id``."""
    deleted = 0
    updated = 0
    qs = JobAssignment.objects.filter(workspace_id=workspace_id).iterator()
    with transaction.atomic():
        for job in qs:
            try:
                cfg = job.get_config()
            except Exception:
                logger.warning(
                    "job_assignment_integration_cleanup: skip job with invalid config job_id=%s workspace_id=%s",
                    job.pk,
                    workspace_id,
                    exc_info=True,
                )
                continue
            if not _job_references_integration_account(cfg, integration_account_id):
                continue
            if _sole_integration_account_in_accounts(cfg, integration_account_id):
                job.delete()
                deleted += 1
                continue
            job.set_config(_strip_integration_account(cfg, integration_account_id))
            job.save()
            updated += 1
    if deleted or updated:
        logger.info(
            "job_assignment_integration_cleanup: workspace_id=%s integration_account_id=%s deleted_jobs=%s updated_jobs=%s",
            workspace_id,
            integration_account_id,
            deleted,
            updated,
        )
