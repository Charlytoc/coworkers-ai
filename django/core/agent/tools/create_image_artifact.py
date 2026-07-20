"""Tool: generate and persist an image artifact for the current ``TaskExecution``."""

from __future__ import annotations

import hashlib
import logging
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile
from pydantic import ValidationError

from core.agent.base import AgentTool, AgentToolConfig
from core.models import Artifact, CyberIdentity, IntegrationAccount, MediaObject, TaskExecution
from core.schemas.agent_tools import CreateImageArtifactArgs
from core.services.openai_service import IMAGE_GENERATION_MODEL, OpenAIService

logger = logging.getLogger(__name__)

_MIME_BY_FORMAT = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


def make_create_image_artifact_tool(*, task_execution: TaskExecution) -> AgentToolConfig:
    """Return a ``create_image_artifact`` tool bound to the current task execution."""

    tool = AgentTool(
        type="function",
        name="create_image_artifact",
        description=(
            "Generate one image with OpenAI and save it as a durable media-backed artifact. "
            f"The only image model available is {IMAGE_GENERATION_MODEL}. "
            "If the image will be published as an Instagram post, use output_format `jpeg`. "
            "For a carousel, call this once per slide with the same `size` and `output_format`, "
            "and reuse the same style description in every prompt so the slides stay consistent."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 32000,
                    "description": "Detailed prompt describing the image to generate.",
                },
                "label": {
                    "type": "string",
                    "maxLength": 200,
                    "default": "",
                    "description": "Optional human-readable label for the artifact.",
                },
                "size": {
                    "type": "string",
                    "enum": ["auto", "1024x1024", "1536x1024", "1024x1536"],
                    "default": "1024x1024",
                },
                "quality": {
                    "type": "string",
                    "enum": ["auto", "low", "medium", "high"],
                    "default": "auto",
                },
                "background": {
                    "type": "string",
                    "enum": ["auto", "transparent", "opaque"],
                    "default": "auto",
                },
                "output_format": {
                    "type": "string",
                    "enum": ["png", "jpeg", "webp"],
                    "default": "png",
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
    )

    def execute(
        prompt: str,
        label: str = "",
        size: str = "1024x1024",
        quality: str = "auto",
        background: str = "auto",
        output_format: str = "png",
    ) -> str:
        try:
            args = CreateImageArtifactArgs(
                prompt=prompt,
                label=label,
                size=size,
                quality=quality,
                background=background,
                output_format=output_format,
            )
        except ValidationError as exc:
            return f"Error: {exc.errors()[0]['msg']}"

        try:
            generated = OpenAIService(settings.OPENAI_API_KEY).generate_image_artifacts(
                prompt=args.prompt,
                size=args.size,
                quality=args.quality,
                background=args.background,
                output_format=args.output_format,
            )
        except Exception as exc:
            logger.exception(
                "create_image_artifact: generation failed task_execution=%s",
                task_execution.id,
            )
            return f"Error: image generation failed: {exc}"

        image_bytes = generated["bytes"]
        extension = generated["output_format"]
        filename = f"generated-{uuid4().hex}.{extension}"
        media = MediaObject.objects.create(
            workspace=task_execution.workspace,
            title=args.label or "Generated image",
            file=ContentFile(image_bytes, name=filename),
            original_filename=filename,
            byte_size=len(image_bytes),
            mime_type=_MIME_BY_FORMAT[extension],
            checksum_sha256=hashlib.sha256(image_bytes).hexdigest(),
            extra={
                "origin": "generated",
                "provider": "openai",
                "model": IMAGE_GENERATION_MODEL,
                "prompt": args.prompt,
                "size": generated["size"],
                "quality": generated["quality"],
                "background": generated["background"],
                "output_format": extension,
            },
        )

        inputs = task_execution.get_inputs()
        identity = None
        identity_config = inputs.identity_config
        if identity_config is not None:
            identity = CyberIdentity.objects.get(
                id=identity_config.identity,
                workspace=task_execution.workspace,
            )

        integration_account = None
        integration_account_id = (
            getattr(inputs.channel, "integration_account_id", None)
            if inputs.channel is not None
            else None
        )
        if integration_account_id is not None:
            integration_account = IntegrationAccount.objects.get(
                id=integration_account_id,
                workspace=task_execution.workspace,
            )

        artifact = Artifact.objects.create(
            workspace=task_execution.workspace,
            task_execution=task_execution,
            identity=identity,
            integration_account=integration_account,
            media=media,
            kind=Artifact.Kind.IMAGE,
            label=args.label,
            metadata={
                "prompt": args.prompt,
                "model": IMAGE_GENERATION_MODEL,
                "size": generated["size"],
                "quality": generated["quality"],
                "background": generated["background"],
                "extension": extension,
                "mime_type": media.mime_type,
                "byte_size": media.byte_size,
                "checksum_sha256": media.checksum_sha256,
                "revised_prompt": generated["revised_prompt"],
                "created": generated["created"],
                "usage": generated["usage"],
            },
        )
        logger.info(
            "create_image_artifact: created artifact=%s media=%s task_execution=%s",
            artifact.id,
            media.id,
            task_execution.id,
        )
        return f"Created image artifact {artifact.id}."

    return AgentToolConfig(tool=tool, function=execute)
