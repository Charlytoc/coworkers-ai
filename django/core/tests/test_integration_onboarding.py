from __future__ import annotations

from unittest.mock import patch

import pydantic
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from core.integrations.actionables import TELEGRAM_REPLY_DM
from core.models import CyberIdentity, IntegrationAccount, JobAssignment, Organization, Workspace
from core.schemas.integration_account import (
    INTEGRATION_ONBOARDING_CONFIG_KEY,
    IntegrationAccountOnboarding,
    LlmDefaultJobCopy,
)
from core.services.instagram_service import consume_oauth_state, store_oauth_state
from core.services.integration_account_onboarding import (
    merge_onboarding_into_config,
    require_cyber_identity_in_workspace,
)
from core.services.integration_default_job_provisioner import provision_default_job_for_integration_account


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class InstagramOauthStateTests(TestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_store_and_consume_round_trip(self) -> None:
        token = store_oauth_state(
            workspace_id=7,
            user_id=3,
            cyber_identity_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            use_case="  Reply to leads  ",
        )
        payload = consume_oauth_state(token)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["workspace_id"], 7)
        self.assertEqual(payload["user_id"], 3)
        self.assertEqual(payload["cyber_identity_id"], "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        self.assertEqual(payload["use_case"], "  Reply to leads  ")
        self.assertIsNone(consume_oauth_state(token))

    def test_consume_missing_returns_none(self) -> None:
        self.assertIsNone(consume_oauth_state("not-a-real-token"))


class IntegrationAccountOnboardingSchemaTests(TestCase):
    def test_use_case_must_be_non_empty_after_strip(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            IntegrationAccountOnboarding.model_validate(
                {"cyber_identity_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "use_case": "   "}
            )


class RequireCyberIdentityInWorkspaceTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="o", domain="o.example.test", status="active")
        self.user = get_user_model().objects.create_user(
            email="u@example.test",
            password="x",
            organization=self.org,
        )
        self.ws1 = Workspace.objects.create(organization=self.org, name="w1")
        self.ws2 = Workspace.objects.create(organization=self.org, name="w2")
        self.identity_ws2 = CyberIdentity.objects.create(
            workspace=self.ws2,
            created_by=self.user,
            type=CyberIdentity.Type.PERSONAL_ASSISTANT,
            display_name="Other",
            is_active=True,
            config={},
        )

    def test_rejects_identity_from_other_workspace(self) -> None:
        with self.assertRaises(ValueError):
            require_cyber_identity_in_workspace(
                workspace_id=self.ws1.id,
                cyber_identity_id=self.identity_ws2.id,
            )


class ProvisionDefaultJobTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="po", domain="po.example.test", status="active")
        self.user = get_user_model().objects.create_user(
            email="p@example.test",
            password="x",
            organization=self.org,
        )
        self.workspace = Workspace.objects.create(organization=self.org, name="pw")
        self.identity = CyberIdentity.objects.create(
            workspace=self.workspace,
            created_by=self.user,
            type=CyberIdentity.Type.PERSONAL_ASSISTANT,
            display_name="Alex",
            is_active=True,
            config={},
        )
        self.account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            created_by=self.user,
            provider=IntegrationAccount.Provider.TELEGRAM,
            external_account_id="botx",
            display_name="Bot X",
            status=IntegrationAccount.Status.ACTIVE,
            encrypted_auth="",
            config={"senders": []},
        )
        onboarding = IntegrationAccountOnboarding(
            cyber_identity_id=self.identity.id,
            use_case="Book demos for SaaS leads",
        )
        self.account.config = merge_onboarding_into_config(self.account.config, onboarding)
        self.account.save()

    @patch("core.services.integration_default_job_provisioner.generate_default_job_copy")
    def test_provision_creates_job_with_llm_copy_and_strips_onboarding(self, mock_llm) -> None:
        mock_llm.return_value = LlmDefaultJobCopy(
            role_name="Lead Booker",
            description="Handles Telegram DMs for demos.",
            instructions="Use send_message for every reply. Be concise.",
        )
        provision_default_job_for_integration_account(integration_account_id=self.account.id)

        job = JobAssignment.objects.get(workspace=self.workspace)
        self.assertEqual(job.role_name, "Lead Booker")
        self.assertEqual(job.description, "Handles Telegram DMs for demos.")
        self.assertEqual(job.instructions, "Use send_message for every reply. Be concise.")

        cfg = job.get_config()
        self.assertEqual(len(cfg.identities), 1)
        self.assertEqual(cfg.identities[0].id, self.identity.id)
        slugs = {a.actionable_slug for a in cfg.actions}
        self.assertIn(TELEGRAM_REPLY_DM.slug, slugs)

        self.account.refresh_from_db()
        self.assertNotIn(INTEGRATION_ONBOARDING_CONFIG_KEY, self.account.config)

    @patch("core.services.integration_default_job_provisioner.generate_default_job_copy")
    def test_idempotent_when_job_already_exists(self, mock_llm) -> None:
        mock_llm.return_value = LlmDefaultJobCopy(
            role_name="R1",
            description="D1",
            instructions="I1",
        )
        provision_default_job_for_integration_account(integration_account_id=self.account.id)
        onboarding = IntegrationAccountOnboarding(
            cyber_identity_id=self.identity.id,
            use_case="Again",
        )
        self.account.config = merge_onboarding_into_config({}, onboarding)
        self.account.save()
        mock_llm.reset_mock()

        provision_default_job_for_integration_account(integration_account_id=self.account.id)

        mock_llm.assert_not_called()
        self.assertEqual(JobAssignment.objects.filter(workspace=self.workspace).count(), 1)
        self.account.refresh_from_db()
        self.assertNotIn(INTEGRATION_ONBOARDING_CONFIG_KEY, self.account.config)
