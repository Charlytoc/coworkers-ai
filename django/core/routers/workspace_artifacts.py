import uuid
from datetime import datetime

from django.db import transaction
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from core.models import Artifact, IntegrationAccount, MediaObject, Workspace
from core.routers.workspaces import _workspace_for_member
from core.services.auth import ApiKeyAuth
from core.services.instagram_graph_api import list_comments
from core.utils.schemas import ErrorResponseSchema

router = Router(tags=["Workspace Artifacts"])


class ArtifactMediaOut(Schema):
    id: uuid.UUID
    display_name: str
    mime_type: str
    byte_size: int | None
    public_url: str | None


class ArtifactIdentityOut(Schema):
    id: uuid.UUID
    type: str
    display_name: str


class ArtifactIntegrationOut(Schema):
    id: uuid.UUID
    provider: str
    display_name: str
    external_account_id: str


class ArtifactTaskExecutionOut(Schema):
    id: uuid.UUID
    name: str
    status: str
    job_assignment_id: uuid.UUID | None
    job_role_name: str


class ArtifactOut(Schema):
    id: uuid.UUID
    workspace_id: int
    kind: str
    label: str
    metadata: dict
    identity: ArtifactIdentityOut | None
    task_execution: ArtifactTaskExecutionOut | None
    media: ArtifactMediaOut | None
    integration_account: ArtifactIntegrationOut | None
    created: datetime
    modified: datetime


class InstagramArtifactCommentOut(Schema):
    id: str
    text: str
    username: str
    timestamp: str | None = None


class InstagramArtifactCommentsResponse(Schema):
    media_id: str
    comments: list[InstagramArtifactCommentOut]


def _normalize_instagram_comment(row: dict) -> InstagramArtifactCommentOut | None:
    if not isinstance(row, dict):
        return None
    cid = str(row.get("id") or "").strip()
    if not cid:
        return None
    text = str(row.get("text") or "")
    username = str(row.get("username") or "").strip()
    ts = row.get("timestamp")
    timestamp = str(ts).strip() if ts is not None and str(ts).strip() else None
    return InstagramArtifactCommentOut(
        id=cid,
        text=text,
        username=username,
        timestamp=timestamp,
    )


def _instagram_post_artifact_or_error(row: Artifact) -> tuple[str, IntegrationAccount]:
    if row.kind != Artifact.Kind.EXTERNAL_RESOURCE:
        raise HttpError(400, "Artifact is not an external resource.")
    meta = row.metadata or {}
    if str(meta.get("provider") or "").strip().lower() != IntegrationAccount.Provider.INSTAGRAM:
        raise HttpError(400, "Artifact is not linked to an Instagram post.")
    if str(meta.get("resource_type") or "").strip() != "instagram.post":
        raise HttpError(400, "Artifact is not an Instagram post.")
    media_id = str(meta.get("external_resource_id") or "").strip()
    if not media_id:
        raise HttpError(400, "Instagram post media id is missing on this artifact.")
    account = row.integration_account
    if account is None:
        raise HttpError(400, "Artifact has no integration account.")
    if account.provider != IntegrationAccount.Provider.INSTAGRAM:
        raise HttpError(400, "Integration account is not Instagram.")
    return media_id, account


def _artifact_response(row: Artifact) -> ArtifactOut:
    task = row.task_execution
    media = row.media
    identity = row.identity
    integration = row.integration_account
    return ArtifactOut(
        id=row.id,
        workspace_id=row.workspace_id,
        kind=row.kind,
        label=row.label or "",
        metadata=row.metadata or {},
        identity=ArtifactIdentityOut(
            id=identity.id,
            type=identity.type,
            display_name=identity.display_name,
        )
        if identity is not None
        else None,
        task_execution=ArtifactTaskExecutionOut(
            id=task.id,
            name=task.name or "",
            status=task.status,
            job_assignment_id=task.job_assignment_id,
            job_role_name=task.job_assignment.role_name if task.job_assignment_id else "",
        )
        if task is not None
        else None,
        media=ArtifactMediaOut(
            id=media.id,
            display_name=media.display_name,
            mime_type=media.mime_type or "",
            byte_size=media.byte_size,
            public_url=media.resolve_public_url(),
        )
        if media is not None
        else None,
        integration_account=ArtifactIntegrationOut(
            id=integration.id,
            provider=integration.provider,
            display_name=integration.display_name or "",
            external_account_id=integration.external_account_id,
        )
        if integration is not None
        else None,
        created=row.created,
        modified=row.modified,
    )


def _delete_artifact_cascade(artifact: Artifact, *, workspace: Workspace) -> None:
    """Deletes the row, linked task (and its artifacts) when present, then media rows no longer referenced."""
    task = artifact.task_execution
    if task is not None:
        media_ids = set(
            Artifact.objects.filter(task_execution_id=task.pk, workspace=workspace)
            .exclude(media_id=None)
            .values_list("media_id", flat=True)
        )
        task.delete()
    else:
        media_ids = {artifact.media_id} if artifact.media_id else set()
        artifact.delete()

    for mid in media_ids:
        if Artifact.objects.filter(media_id=mid).exists():
            continue
        mobj = MediaObject.objects.filter(pk=mid, workspace=workspace).first()
        if mobj is None:
            continue
        if mobj.file:
            mobj.file.delete(save=False)
        mobj.delete()


def _artifact_queryset(workspace: Workspace):
    return (
        Artifact.objects.filter(workspace=workspace)
        .select_related(
            "identity",
            "media",
            "integration_account",
            "task_execution",
            "task_execution__job_assignment",
        )
        .order_by("-created")
    )


@router.get(
    "/{workspace_id}/artifacts/",
    response={
        200: list[ArtifactOut],
        400: ErrorResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def list_workspace_artifacts(
    request,
    workspace_id: int,
    identity_id: uuid.UUID | None = None,
    job_assignment_id: uuid.UUID | None = None,
    integration_account_id: uuid.UUID | None = None,
    kind: str | None = None,
    limit: int = 100,
):
    workspace = _workspace_for_member(request, workspace_id)
    capped = max(1, min(500, int(limit or 100)))

    rows = _artifact_queryset(workspace)
    if identity_id is not None:
        rows = rows.filter(identity_id=identity_id)
    if job_assignment_id is not None:
        rows = rows.filter(task_execution__job_assignment_id=job_assignment_id)
    if integration_account_id is not None:
        rows = rows.filter(integration_account_id=integration_account_id)
    if kind is not None:
        if kind not in Artifact.Kind.values:
            raise HttpError(400, f"Invalid kind. Expected one of: {', '.join(Artifact.Kind.values)}.")
        rows = rows.filter(kind=kind)

    return 200, [_artifact_response(row) for row in rows[:capped]]


@router.get(
    "/{workspace_id}/artifacts/{artifact_id}/",
    response={
        200: ArtifactOut,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def get_workspace_artifact(request, workspace_id: int, artifact_id: uuid.UUID):
    workspace = _workspace_for_member(request, workspace_id)
    row = _artifact_queryset(workspace).filter(id=artifact_id).first()
    if row is None:
        raise HttpError(404, "Artifact not found.")
    return 200, _artifact_response(row)


@router.get(
    "/{workspace_id}/artifacts/{artifact_id}/instagram/comments/",
    response={
        200: InstagramArtifactCommentsResponse,
        400: ErrorResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def get_instagram_artifact_comments(request, workspace_id: int, artifact_id: uuid.UUID):
    workspace = _workspace_for_member(request, workspace_id)
    row = _artifact_queryset(workspace).filter(id=artifact_id).first()
    if row is None:
        raise HttpError(404, "Artifact not found.")
    media_id, account = _instagram_post_artifact_or_error(row)
    try:
        raw = list_comments(account, media_id)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    data = raw.get("data")
    comments: list[InstagramArtifactCommentOut] = []
    if isinstance(data, list):
        for item in data:
            normalized = _normalize_instagram_comment(item)
            if normalized is not None:
                comments.append(normalized)
    return 200, InstagramArtifactCommentsResponse(media_id=media_id, comments=comments)


@router.delete(
    "/{workspace_id}/artifacts/{artifact_id}/",
    response={
        204: None,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def delete_workspace_artifact(request, workspace_id: int, artifact_id: uuid.UUID):
    workspace = _workspace_for_member(request, workspace_id)
    with transaction.atomic():
        row = (
            Artifact.objects.select_for_update()
            .filter(workspace=workspace, id=artifact_id)
            .first()
        )
        if row is None:
            raise HttpError(404, "Artifact not found.")
        _delete_artifact_cascade(row, workspace=workspace)
    return 204, None
