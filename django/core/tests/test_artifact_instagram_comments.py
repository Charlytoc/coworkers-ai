from __future__ import annotations

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from ninja.errors import HttpError

from core.models import Artifact, IntegrationAccount, Organization, OrganizationMember, Role, Workspace, WorkspaceMember
from core.routers.workspace_artifacts import (
    InstagramArtifactCommentsResponse,
    _instagram_post_artifact_or_error,
    _normalize_instagram_comment,
    get_instagram_artifact_comments,
)


class NormalizeInstagramCommentTests(TestCase):
    def test_maps_graph_row(self) -> None:
        out = _normalize_instagram_comment(
            {
                "id": "c1",
                "text": "Nice post",
                "username": "fan1",
                "timestamp": "2026-01-02T12:00:00+0000",
            }
        )
        assert out is not None
        self.assertEqual(out.id, "c1")
        self.assertEqual(out.text, "Nice post")
        self.assertEqual(out.username, "fan1")
        self.assertEqual(out.timestamp, "2026-01-02T12:00:00+0000")

    def test_skips_rows_without_id(self) -> None:
        self.assertIsNone(_normalize_instagram_comment({"text": "orphan"}))


class InstagramPostArtifactValidationTests(TestCase):
    def setUp(self) -> None:
        org = Organization.objects.create(name="ac", domain="ac.example.test", status="active")
        self.workspace = Workspace.objects.create(organization=org, name="w")
        self.account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            provider=IntegrationAccount.Provider.INSTAGRAM,
            external_account_id="ig1",
            config={"capabilities": ["comments"], "ig_user_id": "ig1"},
        )
        self.account.auth = {"access_token": "tok"}
        self.account.save()

    def _instagram_post_artifact(self, **metadata_overrides) -> Artifact:
        metadata = {
            "provider": "instagram",
            "resource_type": "instagram.post",
            "external_resource_id": "17996105003792009",
            "status": "published",
        }
        metadata.update(metadata_overrides)
        return Artifact.objects.create(
            workspace=self.workspace,
            kind=Artifact.Kind.EXTERNAL_RESOURCE,
            label="IG post",
            integration_account=self.account,
            metadata=metadata,
        )

    def test_valid_post_returns_media_id_and_account(self) -> None:
        row = self._instagram_post_artifact()
        media_id, account = _instagram_post_artifact_or_error(row)
        self.assertEqual(media_id, "17996105003792009")
        self.assertEqual(account.id, self.account.id)

    def test_rejects_non_external_resource(self) -> None:
        row = Artifact.objects.create(
            workspace=self.workspace,
            kind=Artifact.Kind.TEXT,
            label="text",
            metadata={"text": "hello"},
        )
        with self.assertRaises(HttpError) as ctx:
            _instagram_post_artifact_or_error(row)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_rejects_missing_external_resource_id(self) -> None:
        row = self._instagram_post_artifact(external_resource_id="")
        with self.assertRaises(HttpError) as ctx:
            _instagram_post_artifact_or_error(row)
        self.assertIn("media id", str(ctx.exception).lower())


class GetInstagramArtifactCommentsEndpointTests(TestCase):
    def setUp(self) -> None:
        self.org = Organization.objects.create(name="ep", domain="ep.example.test", status="active")
        self.user = get_user_model().objects.create_user(
            email="ep@example.test",
            password="x",
            organization=self.org,
        )
        OrganizationMember.objects.create(
            user=self.user,
            organization=self.org,
            status=OrganizationMember.Status.ACTIVE,
        )
        self.workspace = Workspace.objects.create(organization=self.org, name="pw")
        role = Role.objects.create(
            organization=self.org,
            slug="member",
            display_name="Member",
            role_capabilities=[],
        )
        WorkspaceMember.objects.create(
            user=self.user,
            workspace=self.workspace,
            role=role,
            status=WorkspaceMember.Status.ACTIVE,
        )
        self.account = IntegrationAccount.objects.create(
            workspace=self.workspace,
            provider=IntegrationAccount.Provider.INSTAGRAM,
            external_account_id="ig1",
            config={"capabilities": ["comments"], "ig_user_id": "ig1"},
        )
        self.account.auth = {"access_token": "tok"}
        self.account.save()
        self.artifact = Artifact.objects.create(
            workspace=self.workspace,
            kind=Artifact.Kind.EXTERNAL_RESOURCE,
            label="IG post",
            integration_account=self.account,
            metadata={
                "provider": "instagram",
                "resource_type": "instagram.post",
                "external_resource_id": "17996105003792009",
                "status": "published",
            },
        )
        self.text_artifact = Artifact.objects.create(
            workspace=self.workspace,
            kind=Artifact.Kind.TEXT,
            label="note",
            metadata={"text": "hello"},
        )

    def _request(self) -> MagicMock:
        req = MagicMock()
        req.auth = self.user
        req.user = self.user
        req.headers = {"X-Org-Id": str(self.org.id)}
        return req

    @patch("core.routers.workspace_artifacts.list_comments")
    def test_returns_normalized_comments(self, mock_list_comments: MagicMock) -> None:
        mock_list_comments.return_value = {
            "data": [
                {
                    "id": "c99",
                    "text": "Love it",
                    "username": "brand_fan",
                    "timestamp": "2026-03-01T10:00:00+0000",
                }
            ]
        }
        status, body = get_instagram_artifact_comments(
            self._request(),
            self.workspace.id,
            self.artifact.id,
        )
        self.assertEqual(status, 200)
        assert isinstance(body, InstagramArtifactCommentsResponse)
        self.assertEqual(body.media_id, "17996105003792009")
        self.assertEqual(len(body.comments), 1)
        self.assertEqual(body.comments[0].username, "brand_fan")
        mock_list_comments.assert_called_once_with(self.account, "17996105003792009")

    @patch("core.routers.workspace_artifacts.list_comments")
    def test_empty_graph_data_returns_empty_list(self, mock_list_comments: MagicMock) -> None:
        mock_list_comments.return_value = {"data": []}
        status, body = get_instagram_artifact_comments(
            self._request(),
            self.workspace.id,
            self.artifact.id,
        )
        self.assertEqual(status, 200)
        assert isinstance(body, InstagramArtifactCommentsResponse)
        self.assertEqual(body.comments, [])

    def test_non_instagram_artifact_returns_400(self) -> None:
        with self.assertRaises(HttpError) as ctx:
            get_instagram_artifact_comments(
                self._request(),
                self.workspace.id,
                self.text_artifact.id,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    @patch("core.routers.workspace_artifacts.list_comments")
    def test_graph_value_error_becomes_400(self, mock_list_comments: MagicMock) -> None:
        mock_list_comments.side_effect = ValueError("Instagram account lacks capability 'comments'")
        with self.assertRaises(HttpError) as ctx:
            get_instagram_artifact_comments(
                self._request(),
                self.workspace.id,
                self.artifact.id,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("comments", str(ctx.exception).lower())
