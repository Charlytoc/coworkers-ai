"""Publish workspace image artifact(s) to Instagram (manual testing / debugging)."""

from __future__ import annotations

import json
import uuid
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from core.models import Artifact, IntegrationAccount
from core.services.instagram_service import (
    INSTAGRAM_CAROUSEL_MAX_ITEMS,
    get_access_token,
    get_ig_user_id,
    graph_base_for_account,
    instagram_publish_carousel_post,
    instagram_publish_image_post,
)


class Command(BaseCommand):
    help = (
        "Create an Instagram feed post from one image artifact (single post) or several "
        "(carousel, in the given order) using a connected Instagram integration "
        "(matched by external_account_id, i.e. the IG user id stored on the account)."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--external-account-id",
            required=True,
            help="IntegrationAccount.external_account_id for an Instagram row (typically the IG user id).",
        )
        parser.add_argument(
            "--artifact-id",
            required=True,
            type=uuid.UUID,
            action="append",
            dest="artifact_ids",
            help=(
                "UUID of an image artifact to publish. Repeat 2-10 times to publish a carousel; "
                "the order given is the slide order."
            ),
        )
        parser.add_argument(
            "--workspace-id",
            type=int,
            default=None,
            help="Disambiguate when more than one workspace has an Instagram account with the same external id.",
        )
        parser.add_argument(
            "--caption",
            default="",
            help="Optional post caption (empty by default).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        ext_id = str(options["external_account_id"] or "").strip()
        if not ext_id:
            raise CommandError("--external-account-id must be non-empty.")

        artifact_ids: list[uuid.UUID] = options["artifact_ids"]
        if len(artifact_ids) > INSTAGRAM_CAROUSEL_MAX_ITEMS:
            raise CommandError(
                f"At most {INSTAGRAM_CAROUSEL_MAX_ITEMS} artifacts per carousel; got {len(artifact_ids)}."
            )
        if len(set(artifact_ids)) != len(artifact_ids):
            raise CommandError("Duplicate --artifact-id values are not allowed.")
        workspace_id: int | None = options["workspace_id"]
        caption = str(options["caption"] or "").strip()

        qs = IntegrationAccount.objects.filter(
            provider=IntegrationAccount.Provider.INSTAGRAM,
            external_account_id=ext_id,
        ).exclude(status=IntegrationAccount.Status.REVOKED)
        if workspace_id is not None:
            qs = qs.filter(workspace_id=workspace_id)

        count = qs.count()
        if count == 0:
            raise CommandError(
                "No active Instagram IntegrationAccount matches that external_account_id"
                + (f" and workspace_id={workspace_id}." if workspace_id is not None else ".")
            )
        if count > 1:
            raise CommandError(
                f"Multiple ({count}) Instagram accounts match; pass --workspace-id to pick one."
            )
        account = qs.get()

        image_urls: list[str] = []
        for artifact_id in artifact_ids:
            try:
                artifact = Artifact.objects.select_related("media").get(pk=artifact_id)
            except Artifact.DoesNotExist as exc:
                raise CommandError(f"No artifact with id={artifact_id}.") from exc

            if artifact.workspace_id != account.workspace_id:
                raise CommandError(
                    f"Artifact {artifact_id} workspace_id={artifact.workspace_id} does not match "
                    f"integration workspace_id={account.workspace_id}."
                )

            if artifact.kind != Artifact.Kind.IMAGE:
                raise CommandError(
                    f"Artifact {artifact_id} kind must be {Artifact.Kind.IMAGE!r}, got {artifact.kind!r}."
                )
            if artifact.media_id is None or artifact.media is None:
                raise CommandError(f"Artifact {artifact_id} has no media file.")

            image_url = artifact.media.resolve_public_url()
            if not image_url or not image_url.startswith(("http://", "https://")):
                raise CommandError(
                    f"Artifact {artifact_id} media has no public http(s) URL "
                    "(check SITE_URL and storage; Meta must fetch the image)."
                )
            image_urls.append(image_url)

        token = get_access_token(account)
        ig_uid = get_ig_user_id(account)
        if not token or not ig_uid:
            raise CommandError("Instagram access token or ig_user_id missing on the integration account.")

        graph_base = graph_base_for_account(account)
        self.stdout.write(
            f"Publishing {len(artifact_ids)} artifact(s) via integration={account.id} ig_user_id={ig_uid} …"
        )
        try:
            if len(image_urls) == 1:
                response = instagram_publish_image_post(
                    access_token=token,
                    ig_user_id=ig_uid,
                    image_url=image_urls[0],
                    caption=caption,
                    graph_base=graph_base,
                )
            else:
                response = instagram_publish_carousel_post(
                    access_token=token,
                    ig_user_id=ig_uid,
                    image_urls=image_urls,
                    caption=caption,
                    graph_base=graph_base,
                )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        published = response.get("published") or {}
        media_id = published.get("id")
        self.stdout.write(self.style.SUCCESS(f"Published. Instagram media id: {media_id}"))
        self.stdout.write(json.dumps(response, indent=2, default=str))
