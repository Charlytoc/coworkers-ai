"""Create the default DM ``JobAssignment`` after connect, using onboarding + optional LLM copy."""

from __future__ import annotations

import logging
import uuid

from django.db import transaction

from core.models import CyberIdentity, IntegrationAccount
from core.services.integration_account_onboarding import (
    has_default_dm_job_for_integration_account,
    parse_onboarding_from_config,
    pop_onboarding_from_config,
)
from core.services.integration_job_copy_llm import fallback_copy_for_provider, generate_default_job_copy
from core.services.job_assignment_defaults import create_default_dm_job_for_account

logger = logging.getLogger(__name__)


def provision_default_job_for_integration_account(*, integration_account_id: uuid.UUID) -> None:
    account = (
        IntegrationAccount.objects.select_related("workspace")
        .filter(id=integration_account_id)
        .first()
    )
    if account is None:
        logger.warning("provision_default_job: missing account id=%s", integration_account_id)
        return

    if has_default_dm_job_for_integration_account(account):
        logger.info(
            "provision_default_job skip job_exists account_id=%s workspace_id=%s",
            account.id,
            account.workspace_id,
        )
        with transaction.atomic():
            account.config = pop_onboarding_from_config(account.config)
            account.save(update_fields=["config", "modified"])
        return

    onboarding = parse_onboarding_from_config(account.config)
    if onboarding is None:
        logger.warning("provision_default_job skip no_onboarding account_id=%s", account.id)
        return

    identity = CyberIdentity.objects.filter(
        id=onboarding.cyber_identity_id,
        workspace_id=account.workspace_id,
        is_active=True,
    ).first()
    if identity is None:
        logger.error(
            "provision_default_job abort identity_missing account_id=%s identity_id=%s",
            account.id,
            onboarding.cyber_identity_id,
        )
        with transaction.atomic():
            account.config = pop_onboarding_from_config(account.config)
            account.save(update_fields=["config", "modified"])
        return

    copy = generate_default_job_copy(account=account, identity=identity, onboarding=onboarding)
    if copy is None:
        role_name, description, instructions = fallback_copy_for_provider(account)
    else:
        role_name, description, instructions = copy.role_name, copy.description, copy.instructions

    with transaction.atomic():
        create_default_dm_job_for_account(
            account=account,
            identity=identity,
            role_name=role_name,
            description=description,
            instructions=instructions,
            enabled=True,
        )
        account.config = pop_onboarding_from_config(account.config)
        account.save(update_fields=["config", "modified"])

    logger.info(
        "provision_default_job ok account_id=%s workspace_id=%s identity_id=%s",
        account.id,
        account.workspace_id,
        identity.id,
    )
