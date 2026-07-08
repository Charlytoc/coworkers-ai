from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from core.schemas.integration_account import InstagramAuthMethod
from core.services.instagram_capabilities import (
    capabilities_from_scopes,
    default_scopes_for_auth_method,
)
from core.services.instagram_facebook_login import (
    page_option_from_row,
    pages_with_instagram,
    resolve_page_from_pending,
    store_pages_pending,
)
from core.services.instagram_graph_api import list_media
from core.models import Artifact, IntegrationAccount, Organization, Workspace
from core.schemas.integration_account import IntegrationAccountOnboarding
from core.services.instagram_service import (
    _instagram_webhook_subscribed_fields_csv,
    consume_oauth_state,
    disconnect_instagram_account,
    enable_integration_webhook_subscriptions,
    graph_base_for_account,
    instagram_messaging_object_id,
    INSTAGRAM_WEBHOOK_SUBSCRIBED_FIELDS,
    store_oauth_state,
)


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class InstagramOauthStateAuthMethodTests(TestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_store_includes_auth_method(self) -> None:
        token = store_oauth_state(
            workspace_id=1,
            user_id=2,
            cyber_identity_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            use_case="DMs",
            auth_method="facebook_login",
        )
        payload = consume_oauth_state(token)
        assert payload is not None
        self.assertEqual(payload["auth_method"], "facebook_login")


class InstagramWebhookSubscribedFieldsTests(TestCase):
    def test_includes_messages_and_comments(self) -> None:
        self.assertIn("messages", INSTAGRAM_WEBHOOK_SUBSCRIBED_FIELDS)
        self.assertIn("comments", INSTAGRAM_WEBHOOK_SUBSCRIBED_FIELDS)
        self.assertEqual(_instagram_webhook_subscribed_fields_csv(), "messages,comments")


class InstagramCapabilitiesTests(TestCase):
    def test_instagram_login_defaults(self) -> None:
        caps = capabilities_from_scopes(
            auth_method=InstagramAuthMethod.INSTAGRAM_LOGIN,
            granted_scopes=[],
        )
        self.assertIn("publish", caps)
        self.assertIn("dm", caps)
        self.assertNotIn("insights", caps)

    def test_facebook_login_full_scopes(self) -> None:
        scopes = default_scopes_for_auth_method(InstagramAuthMethod.FACEBOOK_LOGIN)
        self.assertIn("pages_manage_metadata", scopes)
        caps = capabilities_from_scopes(
            auth_method=InstagramAuthMethod.FACEBOOK_LOGIN,
            granted_scopes=scopes,
        )
        self.assertIn("insights", caps)
        self.assertIn("comments", caps)
        self.assertIn("delete", caps)


class FacebookPageDiscoveryTests(TestCase):
    def test_pages_with_instagram_filters(self) -> None:
        pages = [
            {"id": "1", "instagram_business_account": {"id": "ig1"}},
            {"id": "2"},
        ]
        out = pages_with_instagram(pages)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "1")

    def test_page_option_from_row(self) -> None:
        row = page_option_from_row(
            {
                "id": "page1",
                "name": "My Page",
                "instagram_business_account": {"id": "ig99", "username": "brand"},
            }
        )
        self.assertEqual(row["page_id"], "page1")
        self.assertEqual(row["ig_username"], "brand")


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class FacebookPagesPendingTests(TestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_resolve_page_from_pending(self) -> None:
        onboarding = IntegrationAccountOnboarding(
            cyber_identity_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            use_case="Full IG",
        )
        pages = [
            {
                "id": "p1",
                "name": "A",
                "access_token": "tok1",
                "instagram_business_account": {"id": "ig1", "username": "a"},
            }
        ]
        pending = store_pages_pending(
            workspace_id=3,
            user_id=4,
            onboarding=onboarding,
            pages=pages,
            user_access_token="user_tok",
        )
        from core.services.instagram_facebook_login import get_pages_pending

        payload = get_pages_pending(pending)
        assert payload is not None
        resolved = resolve_page_from_pending(payload, "p1")
        assert resolved is not None
        row, token = resolved
        self.assertEqual(row["ig_user_id"], "ig1")
        self.assertEqual(token, "tok1")


class GraphBaseForAccountTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="o", domain="o.example.test", status="active")
        self.workspace = Workspace.objects.create(organization=org, name="w")

    def test_facebook_login_uses_facebook_graph(self) -> None:
        account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            provider=IntegrationAccount.Provider.INSTAGRAM,
            external_account_id="ig1",
            config={"auth_method": "facebook_login"},
        )
        self.assertEqual(graph_base_for_account(account), "https://graph.facebook.com")

    def test_instagram_login_uses_instagram_graph(self) -> None:
        account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            provider=IntegrationAccount.Provider.INSTAGRAM,
            external_account_id="ig1",
            config={"auth_method": "instagram_login"},
        )
        self.assertEqual(graph_base_for_account(account), "https://graph.instagram.com")


class InstagramGraphApiCapabilityTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="o2", domain="o2.example.test", status="active")
        self.workspace = Workspace.objects.create(organization=org, name="w2")
        self.lite_account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            provider=IntegrationAccount.Provider.INSTAGRAM,
            external_account_id="ig1",
            config={"capabilities": ["basic", "publish", "dm"], "ig_user_id": "ig1"},
            encrypted_auth="",
        )
        self.lite_account.auth = {"access_token": "tok"}
        self.lite_account.save()

    def test_list_media_requires_basic_capability(self) -> None:
        IntegrationAccount.objects.filter(id=self.lite_account.id).update(
            config={"capabilities": ["publish"], "ig_user_id": "ig1"}
        )
        account = IntegrationAccount.objects.get(id=self.lite_account.id)
        with self.assertRaises(ValueError):
            list_media(account)

    @patch("core.services.instagram_graph_api.requests.get")
    def test_list_media_calls_graph(self, mock_get: MagicMock) -> None:
        mock_get.return_value.json.return_value = {"data": []}
        mock_get.return_value.status_code = 200
        account = IntegrationAccount.objects.get(id=self.lite_account.id)
        data = list_media(account)
        self.assertEqual(data["data"], [])
        self.assertTrue(mock_get.called)


class InstagramDisconnectTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="disc", domain="disc.example.test", status="active")
        self.workspace = Workspace.objects.create(organization=org, name="disc-ws")
        self.account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            provider=IntegrationAccount.Provider.INSTAGRAM,
            external_account_id="ig_disc",
            status=IntegrationAccount.Status.ACTIVE,
            config={"ig_user_id": "ig_disc"},
        )
        self.account.auth = {"access_token": "tok"}
        self.account.save()
        Artifact.objects.create(
            workspace=self.workspace,
            kind=Artifact.Kind.EXTERNAL_RESOURCE,
            integration_account=self.account,
            label="Published post",
            metadata={
                "provider": "instagram",
                "resource_type": "instagram.post",
                "external_resource_id": "17996105003792009",
            },
        )

    @patch("core.services.instagram_service.disable_integration_webhook_subscriptions")
    def test_disconnect_deletes_account_and_linked_artifacts(self, mock_unsub: MagicMock) -> None:
        mock_unsub.return_value = {"success": False}
        account_id = self.account.id
        disconnect_instagram_account(self.account)
        self.assertFalse(IntegrationAccount.objects.filter(id=account_id).exists())
        self.assertEqual(Artifact.objects.filter(workspace=self.workspace).count(), 0)


class IntegrationWebhookSubscriptionRoutingTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="sub", domain="sub.example.test", status="active")
        self.workspace = Workspace.objects.create(organization=org, name="sub-ws")

    @patch("core.services.instagram_service.facebook_enable_page_webhook_subscriptions")
    def test_facebook_login_uses_page_subscribed_apps(self, mock_page_sub: MagicMock) -> None:
        mock_page_sub.return_value = {"success": True}
        account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            provider=IntegrationAccount.Provider.INSTAGRAM,
            external_account_id="ig_page",
            config={
                "auth_method": "facebook_login",
                "facebook_page_id": "page_99",
                "ig_user_id": "ig_page",
            },
        )
        account.auth = {"access_token": "page_tok"}
        account.save()
        result = enable_integration_webhook_subscriptions(account)
        self.assertTrue(result["success"])
        mock_page_sub.assert_called_once_with(page_id="page_99", page_access_token="page_tok")

    @patch("core.services.instagram_service.instagram_enable_webhook_subscriptions")
    def test_instagram_login_uses_ig_user_subscribed_apps(self, mock_ig_sub: MagicMock) -> None:
        mock_ig_sub.return_value = {"success": True}
        account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            provider=IntegrationAccount.Provider.INSTAGRAM,
            external_account_id="ig_lite",
            config={"auth_method": "instagram_login", "ig_user_id": "ig_lite"},
        )
        account.auth = {"access_token": "ig_tok"}
        account.save()
        result = enable_integration_webhook_subscriptions(account)
        self.assertTrue(result["success"])
        mock_ig_sub.assert_called_once_with(
            access_token="ig_tok",
            ig_user_id="ig_lite",
            graph_base="https://graph.instagram.com",
        )


class InstagramMessagingObjectIdTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="msg", domain="msg.example.test", status="active")
        self.workspace = Workspace.objects.create(organization=org, name="msg-ws")

    def test_facebook_login_uses_page_id(self) -> None:
        account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            provider=IntegrationAccount.Provider.INSTAGRAM,
            external_account_id="ig1",
            config={
                "auth_method": "facebook_login",
                "facebook_page_id": "page_123",
                "ig_user_id": "ig1",
            },
        )
        self.assertEqual(instagram_messaging_object_id(account), "page_123")

    def test_instagram_login_uses_ig_user_id(self) -> None:
        account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            provider=IntegrationAccount.Provider.INSTAGRAM,
            external_account_id="ig_lite",
            config={"auth_method": "instagram_login", "ig_user_id": "ig_lite"},
        )
        self.assertEqual(instagram_messaging_object_id(account), "ig_lite")
