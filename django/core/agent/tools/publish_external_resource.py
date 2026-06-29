"""Tool: publish an external resource and persist it as an artifact."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from django.utils import timezone
from pydantic import ValidationError

from core.agent.base import AgentTool, AgentToolConfig
from core.models import Artifact, CyberIdentity, IntegrationAccount, TaskExecution
from core.schemas.agent_tools import PublishExternalResourceArgs
from core.schemas.job_assignment import JobAssignmentAction
from core.services.instagram_service import (
    get_access_token,
    get_ig_user_id,
    graph_base_for_account,
    instagram_publish_image_post,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishTarget:
    target_index: int
    integration_account: IntegrationAccount


def _artifact_media_payload(artifact: Artifact) -> dict[str, Any] | None:
    if artifact.media_id is None or artifact.media is None:
        return None
    return {
        "id": str(artifact.media.id),
        "display_name": artifact.media.display_name,
        "mime_type": artifact.media.mime_type,
        "byte_size": artifact.media.byte_size,
        "public_url": artifact.media.resolve_public_url(),
    }


def _attachment_metadata(
    *,
    artifact: Artifact,
    declared_type: str,
    description: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_id": str(artifact.id),
        "kind": artifact.kind,
        "type": declared_type,
        "description": description,
        "label": artifact.label,
    }
    media = _artifact_media_payload(artifact)
    if media is not None:
        payload["media"] = media
    return payload


def _caption_from_text_attachment(artifact: Artifact) -> str:
    if artifact.kind != Artifact.Kind.TEXT:
        return ""
    text = artifact.metadata.get("text") if isinstance(artifact.metadata, dict) else None
    if not isinstance(text, str):
        return ""
    return text.strip()[:2200]


def _identity_for_task(task_execution: TaskExecution) -> CyberIdentity | None:
    inputs = task_execution.get_inputs()
    identity_config = inputs.identity_config
    if identity_config is None:
        return None
    return CyberIdentity.objects.filter(
        id=identity_config.identity,
        workspace=task_execution.workspace,
    ).first()


def _publish_instagram_post(
    *,
    target: PublishTarget,
    caption: str,
    artifacts_by_id: dict,
    attachments: list,
) -> tuple[str, str, dict[str, Any], list[dict[str, Any]]]:
    image_inputs = [att for att in attachments if att.type == "image"]
    if len(image_inputs) != 1:
        raise ValueError("instagram.post requires exactly one image attachment.")
    image_input = image_inputs[0]
    image = artifacts_by_id.get(image_input.artifact_id)
    if image is None:
        raise ValueError("Image attachment artifact was not found.")
    if image.kind != Artifact.Kind.IMAGE:
        raise ValueError("instagram.post requires one image artifact attachment.")
    if image.media is None:
        raise ValueError("instagram.post image artifact has no media file.")
    image_url = image.media.resolve_public_url()
    if not image_url or not image_url.startswith(("http://", "https://")):
        raise ValueError("instagram.post requires an image artifact with a public HTTP(S) URL.")

    if not caption.strip():
        for att in attachments:
            artifact = artifacts_by_id.get(att.artifact_id)
            if artifact is not None:
                caption = _caption_from_text_attachment(artifact)
                if caption:
                    break

    account = target.integration_account
    access = get_access_token(account)
    ig_uid = get_ig_user_id(account)
    if not access or not ig_uid:
        raise ValueError("Instagram token or ig_user_id not configured.")

    final_caption = caption.strip()
    logger.info(
        "publish_external_resource: publishing instagram.post target_index=%s "
        "account=%s ig_user_id=%s artifact=%s media=%s mime_type=%s byte_size=%s "
        "caption_len=%s image_url=%s",
        target.target_index,
        account.id,
        ig_uid,
        image.id,
        image.media.id,
        image.media.mime_type,
        image.media.byte_size,
        len(final_caption),
        image_url,
    )
    response = instagram_publish_image_post(
        access_token=access,
        ig_user_id=ig_uid,
        image_url=image_url,
        caption=final_caption,
        graph_base=graph_base_for_account(account),
    )
    published_id = str(response.get("published", {}).get("id") or "").strip()
    if not published_id:
        raise ValueError("Instagram publish returned no media id.")

    attachment_metadata = [
        _attachment_metadata(
            artifact=artifacts_by_id[att.artifact_id],
            declared_type=att.type,
            description=att.description,
        )
        for att in attachments
        if att.artifact_id in artifacts_by_id
    ]
    provider_response = {
        "container": response["container"],
        "published": response["published"],
    }
    return published_id, final_caption, provider_response, attachment_metadata


def make_publish_external_resource_tool(
    *,
    task_execution: TaskExecution,
    actions: list[JobAssignmentAction],
) -> AgentToolConfig:
    targets: list[PublishTarget] = []
    seen_accounts: set[str] = set()
    for action in actions:
        account_id = action.integration_account_id
        if account_id is None:
            continue
        key = str(account_id)
        if key in seen_accounts:
            continue
        account = IntegrationAccount.objects.filter(
            id=account_id,
            workspace=task_execution.workspace,
            provider=IntegrationAccount.Provider.INSTAGRAM,
        ).first()
        if account is None:
            continue
        seen_accounts.add(key)
        targets.append(PublishTarget(target_index=len(targets), integration_account=account))

    lines = "\n".join(
        (
            f"- {t.target_index}: [instagram] "
            f"{t.integration_account.display_name or t.integration_account.external_account_id}"
        )
        for t in targets
    )
    tool = AgentTool(
        type="function",
        name="publish_external_resource",
        description=(
            "Publish a durable external resource and save it as an external_resource artifact. "
            "For v1 the only resource_type is `instagram.post`. Instagram posts require exactly "
            "one image artifact with a public HTTP(S) URL. If you generate the image yourself for "
            "Instagram, prefer `create_image_artifact` with output_format `jpeg`.\n\n"
            f"Publishing targets for this run:\n{lines}"
        ),
        parameters={
            "type": "object",
            "properties": {
                "target_index": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Index of the publishing target listed in the tool description.",
                },
                "resource_type": {
                    "type": "string",
                    "enum": ["instagram.post"],
                    "description": "External resource type to create.",
                },
                "caption": {
                    "type": "string",
                    "maxLength": 2200,
                    "default": "",
                    "description": "Caption/body to publish. Optional when a text attachment contains the caption.",
                },
                "attachments": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "artifact_id": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": ["image", "video", "audio", "document", "text"],
                            },
                            "description": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 500,
                            },
                        },
                        "required": ["artifact_id", "type", "description"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["target_index", "resource_type", "attachments"],
            "additionalProperties": False,
        },
    )
    by_index = {t.target_index: t for t in targets}

    def execute(
        target_index: int,
        resource_type: str,
        attachments: list[dict[str, Any]],
        caption: str = "",
    ) -> str:
        try:
            args = PublishExternalResourceArgs(
                target_index=target_index,
                resource_type=resource_type,
                caption=caption,
                attachments=attachments,
            )
        except ValidationError as exc:
            return f"Error: {exc.errors()[0]['msg']}"

        target = by_index.get(args.target_index)
        if target is None:
            return f"Error: invalid target_index={args.target_index}. Valid indices: {sorted(by_index.keys())}."

        artifact_ids = [att.artifact_id for att in args.attachments]
        rows = list(
            Artifact.objects.filter(
                id__in=artifact_ids,
                workspace=task_execution.workspace,
            )
            .select_related("media")
            .order_by("created")
        )
        artifacts_by_id = {row.id: row for row in rows}
        missing = [str(aid) for aid in artifact_ids if aid not in artifacts_by_id]
        if missing:
            return f"Error: artifacts not found in this workspace: {', '.join(missing)}."

        for att in args.attachments:
            artifact = artifacts_by_id[att.artifact_id]
            if artifact.kind != att.type:
                return (
                    "Error: attachment type mismatch for artifact "
                    f"{artifact.id}: declared {att.type!r}, actual {artifact.kind!r}."
                )

        try:
            (
                external_resource_id,
                final_caption,
                provider_response,
                attachment_metadata,
            ) = _publish_instagram_post(
                target=target,
                caption=args.caption,
                artifacts_by_id=artifacts_by_id,
                attachments=args.attachments,
            )
        except ValueError as exc:
            return f"Error: {exc}"

        account = target.integration_account
        artifact = Artifact.objects.create(
            workspace=task_execution.workspace,
            task_execution=task_execution,
            identity=_identity_for_task(task_execution),
            integration_account=account,
            kind=Artifact.Kind.EXTERNAL_RESOURCE,
            label="Instagram post",
            metadata={
                "resource_type": args.resource_type,
                "external_resource_id": external_resource_id,
                "provider": account.provider,
                "status": "published",
                "caption": final_caption,
                "attachments": attachment_metadata,
                "provider_response": provider_response,
                "published_at": timezone.now().isoformat(),
            },
        )
        logger.info(
            "publish_external_resource: created artifact=%s resource_type=%s external_id=%s",
            artifact.id,
            args.resource_type,
            external_resource_id,
        )
        return f"Published {args.resource_type} and created external resource artifact {artifact.id}."

    return AgentToolConfig(tool=tool, function=execute)
