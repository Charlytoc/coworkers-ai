"""Celery: provision default DM job after integration connect (LLM copy + deterministic config)."""

from __future__ import annotations

import uuid

from celery import shared_task
from celery.utils.log import get_task_logger

from core.services.integration_default_job_provisioner import (
    provision_default_job_for_integration_account as _provision,
)

logger = get_task_logger(__name__)


@shared_task
def provision_integration_default_job(integration_account_id: str) -> None:
    try:
        aid = uuid.UUID(str(integration_account_id))
    except (TypeError, ValueError):
        logger.warning("provision_integration_default_job invalid uuid=%r", integration_account_id)
        return
    _provision(integration_account_id=aid)
