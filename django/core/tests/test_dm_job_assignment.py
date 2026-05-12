from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from ninja.errors import HttpError

from core.integrations.actionables import TELEGRAM_REPLY_DM, TELEGRAM_SEND_DIRECT_DM
from core.integrations.workspace_actionables import validate_job_assignment_config
from core.models import (
    Conversation,
    CyberIdentity,
    IntegrationAccount,
    JobAssignment,
    Organization,
    Workspace,
)
from core.schemas.conversation import ConversationConfig
from core.schemas.integration_account import SenderApprovalStatus
from core.schemas.job_assignment import (
    JobAssignmentAction,
    JobAssignmentActionDirectRecipient,
    JobAssignmentConfig,
    JobAssignmentConfigAccount,
    JobAssignmentConfigIdentity,
)
from core.services.send_targets import collect_resolved_send_targets


def _sender_row(thread_id: str, status: SenderApprovalStatus) -> dict:
    return {
        "external_thread_id": thread_id,
        "approval_status": status.value,
        "handle": None,
        "extractions": {},
        "first_seen_at": None,
        "last_seen_at": None,
    }


class DmJobAssignmentValidationTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="o", domain="o.example.test", status="active")
        self.user = get_user_model().objects.create_user(
            email="t@example.test",
            password="x",
            organization=self.org,
        )
        self.workspace = Workspace.objects.create(organization=self.org, name="w")
        self.identity = CyberIdentity.objects.create(
            workspace=self.workspace,
            created_by=self.user,
            type=CyberIdentity.Type.PERSONAL_ASSISTANT,
            display_name="Bot",
            is_active=True,
            config={},
        )
        self.account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            created_by=self.user,
            provider=IntegrationAccount.Provider.TELEGRAM,
            external_account_id="bot1",
            display_name="Bot",
            status=IntegrationAccount.Status.ACTIVE,
            encrypted_auth="",
            config={"senders": [_sender_row("111", SenderApprovalStatus.APPROVED)]},
        )

    def test_direct_recipients_rejected_on_reply_action(self) -> None:
        cfg = JobAssignmentConfig(
            accounts=[JobAssignmentConfigAccount(id=self.account.id, provider="telegram")],
            identities=[
                JobAssignmentConfigIdentity(
                    id=self.identity.id, type="personal_assistant", config={}
                )
            ],
            triggers=[],
            actions=[
                JobAssignmentAction(
                    actionable_slug=TELEGRAM_REPLY_DM.slug,
                    integration_account_id=self.account.id,
                    direct_dm_recipients=[
                        JobAssignmentActionDirectRecipient(external_thread_id="999", label="x")
                    ],
                ),
            ],
        )
        with self.assertRaises(HttpError) as ctx:
            validate_job_assignment_config(workspace=self.workspace, config=cfg)
        self.assertIn("direct_dm_recipients", str(ctx.exception).lower())

    def test_direct_action_requires_recipients(self) -> None:
        cfg = JobAssignmentConfig(
            accounts=[JobAssignmentConfigAccount(id=self.account.id, provider="telegram")],
            identities=[
                JobAssignmentConfigIdentity(
                    id=self.identity.id, type="personal_assistant", config={}
                )
            ],
            triggers=[],
            actions=[
                JobAssignmentAction(
                    actionable_slug=TELEGRAM_SEND_DIRECT_DM.slug,
                    integration_account_id=self.account.id,
                    direct_dm_recipients=[],
                ),
            ],
        )
        with self.assertRaises(HttpError) as ctx:
            validate_job_assignment_config(workspace=self.workspace, config=cfg)
        self.assertIn("direct_dm_recipients", str(ctx.exception).lower())


class CollectResolvedSendTargetsTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="o2", domain="o2.example.test", status="active")
        self.user = get_user_model().objects.create_user(
            email="t2@example.test",
            password="x",
            organization=self.org,
        )
        self.workspace = Workspace.objects.create(organization=self.org, name="w2")
        self.identity = CyberIdentity.objects.create(
            workspace=self.workspace,
            created_by=self.user,
            type=CyberIdentity.Type.PERSONAL_ASSISTANT,
            display_name="Bot",
            is_active=True,
            config={},
        )
        self.account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            created_by=self.user,
            provider=IntegrationAccount.Provider.TELEGRAM,
            external_account_id="bot2",
            display_name="Bot",
            status=IntegrationAccount.Status.ACTIVE,
            encrypted_auth="",
            config={
                "senders": [
                    _sender_row("111", SenderApprovalStatus.APPROVED),
                    _sender_row("222", SenderApprovalStatus.APPROVED),
                ]
            },
        )
        self.job = JobAssignment.objects.create(
            workspace=self.workspace,
            role_name="r",
            description="",
            instructions="",
            enabled=True,
        )
        cfg = JobAssignmentConfig(
            accounts=[JobAssignmentConfigAccount(id=self.account.id, provider="telegram")],
            identities=[
                JobAssignmentConfigIdentity(
                    id=self.identity.id, type="personal_assistant", config={}
                )
            ],
            triggers=[],
            actions=[
                JobAssignmentAction(
                    actionable_slug=TELEGRAM_REPLY_DM.slug,
                    integration_account_id=self.account.id,
                ),
                JobAssignmentAction(
                    actionable_slug=TELEGRAM_SEND_DIRECT_DM.slug,
                    integration_account_id=self.account.id,
                    direct_dm_recipients=[
                        JobAssignmentActionDirectRecipient(external_thread_id="222", label="Other"),
                    ],
                ),
            ],
        )
        self.job.set_config(cfg)
        self.job.save()
        self.conv = Conversation.objects.create(
            workspace=self.workspace,
            origin=Conversation.Origin.INTEGRATION,
            integration_account=self.account,
            cyber_identity=self.identity,
            status=Conversation.Status.ACTIVE,
            config={},
        )
        self.conv.set_config(
            ConversationConfig(
                external_thread_id="111",
                external_user_id="111",
            )
        )
        self.conv.save()

    def test_reply_and_direct_deduped_by_thread(self) -> None:
        cfg = JobAssignmentConfig(
            accounts=[JobAssignmentConfigAccount(id=self.account.id, provider="telegram")],
            identities=[
                JobAssignmentConfigIdentity(
                    id=self.identity.id, type="personal_assistant", config={}
                )
            ],
            triggers=[],
            actions=[
                JobAssignmentAction(
                    actionable_slug=TELEGRAM_REPLY_DM.slug,
                    integration_account_id=self.account.id,
                ),
                JobAssignmentAction(
                    actionable_slug=TELEGRAM_SEND_DIRECT_DM.slug,
                    integration_account_id=self.account.id,
                    direct_dm_recipients=[
                        JobAssignmentActionDirectRecipient(external_thread_id="111", label="dup"),
                    ],
                ),
            ],
        )
        self.job.set_config(cfg)
        self.job.save()
        job = JobAssignment.objects.get(pk=self.job.pk)
        targets = collect_resolved_send_targets(
            job=job,
            conversation=self.conv,
            actions=job.get_config().actions,
        )
        kinds = {t.external_thread_id: t.target_kind for t in targets}
        self.assertEqual(set(kinds.keys()), {"111"})
        self.assertEqual(kinds["111"], "reply")

    def test_reply_plus_distinct_direct(self) -> None:
        job = JobAssignment.objects.get(pk=self.job.pk)
        targets = collect_resolved_send_targets(
            job=job,
            conversation=self.conv,
            actions=job.get_config().actions,
        )
        by_thread = {t.external_thread_id: t.target_kind for t in targets}
        self.assertEqual(by_thread["111"], "reply")
        self.assertEqual(by_thread["222"], "direct")


class SendDirectMessageToolTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="o3", domain="o3.example.test", status="active")
        self.user = get_user_model().objects.create_user(
            email="t3@example.test",
            password="x",
            organization=self.org,
        )
        self.workspace = Workspace.objects.create(organization=self.org, name="w3")
        self.identity = CyberIdentity.objects.create(
            workspace=self.workspace,
            created_by=self.user,
            type=CyberIdentity.Type.PERSONAL_ASSISTANT,
            display_name="Bot",
            is_active=True,
            config={},
        )
        self.account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            created_by=self.user,
            provider=IntegrationAccount.Provider.TELEGRAM,
            external_account_id="bot3",
            display_name="Bot",
            status=IntegrationAccount.Status.ACTIVE,
            encrypted_auth="",
            config={"senders": []},
        )

    @patch("core.agent.tools.send_message.telegram_send_message", return_value={"ok": True})
    @patch("core.agent.tools.send_message.get_bot_token", return_value="tok")
    def test_send_direct_creates_conversation(self, _tok, _send) -> None:
        from core.agent.tools.send_message import make_send_direct_message_tool
        from core.schemas.send_target import ResolvedSendTarget, SendTargetProvider

        tid = "555"
        target = ResolvedSendTarget(
            target_index=0,
            target_role="Direct",
            provider=SendTargetProvider.TELEGRAM,
            integration_account_id=self.account.id,
            external_thread_id=tid,
            target_kind="direct",
        )
        cfg = make_send_direct_message_tool(
            targets=[target],
            cyber_identity=self.identity,
            conversation_for_append=None,
        )
        out = cfg.function(target_index=0, message="hello")
        self.assertIn("success", out.lower())
        conv = (
            Conversation.objects.filter(
                integration_account=self.account,
                cyber_identity=self.identity,
            )
            .order_by("-created")
            .first()
        )
        self.assertIsNotNone(conv)
        convo_cfg = conv.get_config()
        self.assertEqual(convo_cfg.external_thread_id.strip(), tid)
