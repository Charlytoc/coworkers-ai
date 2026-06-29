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
from core.models import IntegrationAccount, Organization, Workspace
from core.schemas.integration_account import IntegrationAccountOnboarding
from core.services.instagram_service import consume_oauth_state, graph_base_for_account, store_oauth_state


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
