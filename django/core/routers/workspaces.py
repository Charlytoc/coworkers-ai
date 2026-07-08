import uuid
from datetime import datetime

from django.db import models, transaction
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from pydantic import ValidationError

from core.integrations.workspace_actionables import (
    append_default_event_triggers_if_empty,
    assert_unique_inbound_event_listeners,
    list_actionable_catalog_for_workspace,
    validate_job_assignment_config,
)
from core.models import (
    Conversation,
    CyberIdentity,
    IntegrationAccount,
    JobAssignment,
    Message,
    Role,
    TaskExecution,
    Workspace,
    WorkspaceMember,
)
from core.schemas.cyber_identity import CyberIdentityConfig
from core.schemas.job_assignment import JobAssignmentConfig
from core.services.auth import ApiKeyAuth, auth_service
from core.utils.schemas import ErrorResponseSchema

router = Router(tags=["Workspaces"])


class WorkspaceCreateRequest(Schema):
    name: str


class WorkspaceUpdateRequest(Schema):
    name: str


class WorkspaceResponse(Schema):
    id: int
    name: str
    organization_id: str


def _workspace_response(ws: Workspace) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=ws.id,
        name=ws.name,
        organization_id=str(ws.organization_id),
    )


def _default_member_role(organization):
    role, _ = Role.objects.get_or_create(
        organization=organization,
        slug="member",
        defaults={
            "display_name": "Member",
            "role_capabilities": [],
        },
    )
    return role


def _workspace_for_member(request, workspace_id: int) -> Workspace:
    user = auth_service.get_user_from_request(request)
    org = auth_service.get_active_organization(request)
    workspace = Workspace.objects.filter(id=workspace_id, organization=org).first()
    if workspace is None:
        raise HttpError(404, "Workspace not found.")
    member = WorkspaceMember.objects.filter(
        user=user,
        workspace=workspace,
        status=WorkspaceMember.Status.ACTIVE,
    ).first()
    if member is None:
        raise HttpError(403, "You are not an active member of this workspace.")
    return workspace


class IntegrationAccountListItem(Schema):
    id: uuid.UUID
    provider: str
    display_name: str
    status: str
    external_account_id: str
    created: datetime


@router.get(
    "/{workspace_id}/integrations/",
    response={
        200: list[IntegrationAccountListItem],
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def list_workspace_integrations(request, workspace_id: int):
    workspace = _workspace_for_member(request, workspace_id)
    rows = (
        IntegrationAccount.objects.filter(workspace=workspace)
        .exclude(status=IntegrationAccount.Status.REVOKED)
        .order_by("-created")
    )
    return 200, [
        IntegrationAccountListItem(
            id=row.id,
            provider=row.provider,
            display_name=row.display_name or "",
            status=row.status,
            external_account_id=row.external_account_id,
            created=row.created,
        )
        for row in rows
    ]


class IntegrationAccountSenderOut(Schema):
    external_thread_id: str
    approval_status: str
    handle: str | None = None
    extractions: dict = {}
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class IntegrationAccountDetail(Schema):
    id: uuid.UUID
    workspace_id: int
    provider: str
    display_name: str
    status: str
    external_account_id: str
    config: dict
    senders: list[IntegrationAccountSenderOut]
    last_synced_at: datetime | None
    last_error: str
    created: datetime
    modified: datetime


def _serialize_senders(row: IntegrationAccount) -> list[IntegrationAccountSenderOut]:
    from core.services.integration_senders import list_senders

    return [
        IntegrationAccountSenderOut(
            external_thread_id=s.external_thread_id,
            approval_status=s.approval_status.value,
            handle=s.handle,
            extractions=s.extractions or {},
            first_seen_at=s.first_seen_at,
            last_seen_at=s.last_seen_at,
        )
        for s in list_senders(row)
    ]


def _integration_account_detail(row: IntegrationAccount) -> IntegrationAccountDetail:
    return IntegrationAccountDetail(
        id=row.id,
        workspace_id=row.workspace_id,
        provider=row.provider,
        display_name=row.display_name or "",
        status=row.status,
        external_account_id=row.external_account_id,
        config=row.config or {},
        senders=_serialize_senders(row),
        last_synced_at=row.last_synced_at,
        last_error=row.last_error or "",
        created=row.created,
        modified=row.modified,
    )


@router.get(
    "/{workspace_id}/integrations/{integration_account_id}/",
    response={
        200: IntegrationAccountDetail,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def get_workspace_integration(request, workspace_id: int, integration_account_id: uuid.UUID):
    workspace = _workspace_for_member(request, workspace_id)
    row = IntegrationAccount.objects.filter(id=integration_account_id, workspace=workspace).first()
    if row is None:
        raise HttpError(404, "Integration account not found.")
    return 200, _integration_account_detail(row)


class TaskExecutionListItem(Schema):
    id: uuid.UUID
    status: str
    requires_approval: bool
    job_assignment_id: uuid.UUID | None
    job_role_name: str
    scheduled_to: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created: datetime


def _jobs_bound_to_account(workspace: Workspace, account_id: uuid.UUID) -> list[uuid.UUID]:
    """Return job-assignment ids in ``workspace`` that reference ``account_id`` in their config.

    A job is considered bound to the account when either:
    - ``config.accounts[]`` contains ``{id: <account_id>}``, or
    - ``config.actions[]`` contains ``{integration_account_id: <account_id>}``.
    """
    account_str = str(account_id)
    jobs = JobAssignment.objects.filter(workspace=workspace).only("id", "config")
    ids: list[uuid.UUID] = []
    for job in jobs:
        cfg = job.config or {}
        accounts = cfg.get("accounts") or []
        actions = cfg.get("actions") or []
        if any(str((a or {}).get("id")) == account_str for a in accounts):
            ids.append(job.id)
            continue
        if any(str((a or {}).get("integration_account_id")) == account_str for a in actions):
            ids.append(job.id)
    return ids


@router.get(
    "/{workspace_id}/integrations/{integration_account_id}/task-executions/",
    response={
        200: list[TaskExecutionListItem],
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def list_integration_task_executions(
    request,
    workspace_id: int,
    integration_account_id: uuid.UUID,
    limit: int = 100,
):
    workspace = _workspace_for_member(request, workspace_id)
    account = IntegrationAccount.objects.filter(id=integration_account_id, workspace=workspace).first()
    if account is None:
        raise HttpError(404, "Integration account not found.")

    job_ids = _jobs_bound_to_account(workspace, account.id)
    if not job_ids:
        return 200, []

    capped = max(1, min(500, int(limit or 100)))
    rows = (
        TaskExecution.objects.filter(workspace=workspace, job_assignment_id__in=job_ids)
        .select_related("job_assignment")
        .order_by("-created")[:capped]
    )
    return 200, [
        TaskExecutionListItem(
            id=row.id,
            status=row.status,
            requires_approval=row.requires_approval,
            job_assignment_id=row.job_assignment_id,
            job_role_name=(row.job_assignment.role_name if row.job_assignment_id else ""),
            scheduled_to=row.scheduled_to,
            started_at=row.started_at,
            completed_at=row.completed_at,
            created=row.created,
        )
        for row in rows
    ]


class ConversationListItem(Schema):
    id: uuid.UUID
    status: str
    cyber_identity_id: uuid.UUID
    cyber_identity_name: str
    external_thread_id: str
    external_user_id: str
    message_count: int
    last_interaction_at: datetime | None
    created: datetime


@router.get(
    "/{workspace_id}/integrations/{integration_account_id}/conversations/",
    response={
        200: list[ConversationListItem],
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def list_integration_conversations(
    request,
    workspace_id: int,
    integration_account_id: uuid.UUID,
    limit: int = 100,
):
    workspace = _workspace_for_member(request, workspace_id)
    account = IntegrationAccount.objects.filter(id=integration_account_id, workspace=workspace).first()
    if account is None:
        raise HttpError(404, "Integration account not found.")

    capped = max(1, min(500, int(limit or 100)))
    rows = (
        Conversation.objects.filter(workspace=workspace, integration_account=account)
        .select_related("cyber_identity")
        .order_by("-last_interaction_at", "-created")[:capped]
    )
    msg_counts = dict(
        Message.objects.filter(conversation__in=rows)
        .values_list("conversation_id")
        .annotate(count=models.Count("id"))
        .values_list("conversation_id", "count")
    ) if rows else {}

    items: list[ConversationListItem] = []
    for row in rows:
        cfg = row.config or {}
        items.append(
            ConversationListItem(
                id=row.id,
                status=row.status,
                cyber_identity_id=row.cyber_identity_id,
                cyber_identity_name=row.cyber_identity.display_name if row.cyber_identity_id else "",
                external_thread_id=str(cfg.get("external_thread_id", "")),
                external_user_id=str(cfg.get("external_user_id", "")),
                message_count=int(msg_counts.get(row.id, 0)),
                last_interaction_at=row.last_interaction_at,
                created=row.created,
            )
        )
    return 200, items


@router.get(
    "",
    response={200: list[WorkspaceResponse], 401: ErrorResponseSchema},
    auth=[ApiKeyAuth(), django_auth],
)
def list_workspaces(request):
    user = auth_service.get_user_from_request(request)
    org = auth_service.get_active_organization(request)
    qs = (
        Workspace.objects.filter(
            organization=org,
            workspace_members__user=user,
            workspace_members__status=WorkspaceMember.Status.ACTIVE,
        )
        .distinct()
        .order_by("name")
    )
    return 200, [_workspace_response(w) for w in qs]


@router.post(
    "",
    response={201: WorkspaceResponse, 400: ErrorResponseSchema, 401: ErrorResponseSchema},
    auth=[ApiKeyAuth(), django_auth],
)
def create_workspace(request, data: WorkspaceCreateRequest):
    name = (data.name or "").strip()
    if not name:
        return 400, ErrorResponseSchema(error="Workspace name is required.", error_code="WORKSPACE_NAME_REQUIRED")

    user = auth_service.get_user_from_request(request)
    org = auth_service.get_active_organization(request)
    role = _default_member_role(org)

    with transaction.atomic():
        ws = Workspace.objects.create(organization=org, name=name[: Workspace._meta.get_field("name").max_length])
        WorkspaceMember.objects.create(
            user=user,
            workspace=ws,
            role=role,
            status=WorkspaceMember.Status.ACTIVE,
            joined_at=timezone.now(),
        )

    return 201, _workspace_response(ws)


@router.patch(
    "/{workspace_id}/",
    response={
        200: WorkspaceResponse,
        400: ErrorResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def update_workspace(request, workspace_id: int, data: WorkspaceUpdateRequest):
    workspace = _workspace_for_member(request, workspace_id)
    name = (data.name or "").strip()
    if not name:
        return 400, ErrorResponseSchema(error="Workspace name is required.", error_code="WORKSPACE_NAME_REQUIRED")
    workspace.name = name[: Workspace._meta.get_field("name").max_length]
    workspace.save(update_fields=["name", "modified"])
    workspace.refresh_from_db()
    return 200, _workspace_response(workspace)


CYBER_IDENTITY_TYPES = [t.value for t in CyberIdentity.Type]


class CyberIdentityResponse(Schema):
    id: uuid.UUID
    workspace_id: int
    type: str
    display_name: str
    is_active: bool
    config: dict
    created: datetime


class CyberIdentityCreateRequest(Schema):
    type: str
    display_name: str
    is_active: bool = True
    config: dict = {}


class CyberIdentityUpdateRequest(Schema):
    type: str | None = None
    display_name: str | None = None
    is_active: bool | None = None
    config: dict | None = None


def _cyber_identity_response(row: CyberIdentity) -> CyberIdentityResponse:
    return CyberIdentityResponse(
        id=row.id,
        workspace_id=row.workspace_id,
        type=row.type,
        display_name=row.display_name,
        is_active=row.is_active,
        config=row.config or {},
        created=row.created,
    )


def _validate_type(value: str) -> str:
    if value not in CYBER_IDENTITY_TYPES:
        raise HttpError(400, f"Invalid type. Expected one of: {', '.join(CYBER_IDENTITY_TYPES)}.")
    return value


def _validate_cyber_identity_config(cfg: dict) -> dict:
    try:
        parsed = CyberIdentityConfig.model_validate(cfg or {})
    except ValidationError as exc:
        parts = [f"{list(e.get('loc', ()))}: {e.get('msg')}" for e in exc.errors()]
        raise HttpError(400, "; ".join(parts) if parts else str(exc)) from exc
    return parsed.model_dump(mode="json", exclude_none=False)


@router.get(
    "/{workspace_id}/cyber-identities/",
    response={
        200: list[CyberIdentityResponse],
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def list_cyber_identities(request, workspace_id: int):
    workspace = _workspace_for_member(request, workspace_id)
    rows = CyberIdentity.objects.filter(workspace=workspace).order_by("display_name")
    return 200, [_cyber_identity_response(r) for r in rows]


@router.post(
    "/{workspace_id}/cyber-identities/",
    response={
        201: CyberIdentityResponse,
        400: ErrorResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def create_cyber_identity(request, workspace_id: int, data: CyberIdentityCreateRequest):
    workspace = _workspace_for_member(request, workspace_id)
    user = auth_service.get_user_from_request(request)
    display_name = (data.display_name or "").strip()
    if not display_name:
        return 400, ErrorResponseSchema(error="display_name is required.", error_code="DISPLAY_NAME_REQUIRED")
    _validate_type(data.type)
    row = CyberIdentity(
        workspace=workspace,
        created_by=user if getattr(user, "pk", None) else None,
        type=data.type,
        display_name=display_name[:200],
        is_active=data.is_active,
        config=_validate_cyber_identity_config(data.config or {}),
    )
    row.save()
    return 201, _cyber_identity_response(row)


@router.patch(
    "/{workspace_id}/cyber-identities/{cyber_identity_id}/",
    response={
        200: CyberIdentityResponse,
        400: ErrorResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def update_cyber_identity(
    request,
    workspace_id: int,
    cyber_identity_id: uuid.UUID,
    data: CyberIdentityUpdateRequest,
):
    workspace = _workspace_for_member(request, workspace_id)
    row = CyberIdentity.objects.filter(id=cyber_identity_id, workspace=workspace).first()
    if row is None:
        raise HttpError(404, "Cyber identity not found.")

    if data.type is not None:
        _validate_type(data.type)
        row.type = data.type
    if data.display_name is not None:
        name = data.display_name.strip()
        if not name:
            return 400, ErrorResponseSchema(error="display_name cannot be empty.", error_code="DISPLAY_NAME_REQUIRED")
        row.display_name = name[:200]
    if data.is_active is not None:
        row.is_active = data.is_active
    if data.config is not None:
        row.config = _validate_cyber_identity_config(data.config)
    row.save()
    return 200, _cyber_identity_response(row)


@router.delete(
    "/{workspace_id}/cyber-identities/{cyber_identity_id}/",
    response={204: None, 401: ErrorResponseSchema, 403: ErrorResponseSchema, 404: ErrorResponseSchema},
    auth=[ApiKeyAuth(), django_auth],
)
def delete_cyber_identity(request, workspace_id: int, cyber_identity_id: uuid.UUID):
    workspace = _workspace_for_member(request, workspace_id)
    row = CyberIdentity.objects.filter(id=cyber_identity_id, workspace=workspace).first()
    if row is None:
        raise HttpError(404, "Cyber identity not found.")
    row.delete()
    return 204, None


class ActionableCatalogItem(Schema):
    slug: str
    name: str
    description: str
    provider: str
    integration_account_id: str | None = None
    integration: dict | None = None
    required_capability: str | None = None
    available: bool = True
    unavailable_reason: str | None = None


@router.get(
    "/{workspace_id}/actionables/",
    response={
        200: list[ActionableCatalogItem],
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def list_workspace_actionables(request, workspace_id: int):
    workspace = _workspace_for_member(request, workspace_id)
    raw = list_actionable_catalog_for_workspace(workspace)
    return 200, [ActionableCatalogItem(**row) for row in raw]


class JobAssignmentResponse(Schema):
    id: uuid.UUID
    workspace_id: int
    role_name: str
    description: str
    instructions: str
    enabled: bool
    config: dict
    identity_id: uuid.UUID | None
    created: datetime


def _job_assignment_response(row: JobAssignment) -> JobAssignmentResponse:
    return JobAssignmentResponse(
        id=row.id,
        workspace_id=row.workspace_id,
        role_name=row.role_name,
        description=row.description or "",
        instructions=row.instructions or "",
        enabled=row.enabled,
        config=row.config or {},
        identity_id=row.identity_id,
        created=row.created,
    )


class JobAssignmentCreateRequest(Schema):
    role_name: str
    description: str = ""
    instructions: str = ""
    enabled: bool = True
    config: dict = {}
    identity_id: uuid.UUID | None = None


class JobAssignmentUpdateRequest(Schema):
    role_name: str | None = None
    description: str | None = None
    instructions: str | None = None
    enabled: bool | None = None
    config: dict | None = None
    identity_id: uuid.UUID | None = None


def _parse_job_config(cfg: dict) -> JobAssignmentConfig:
    try:
        return JobAssignmentConfig.model_validate(cfg or {})
    except ValidationError as exc:
        parts = [f"{list(e.get('loc', ()))}: {e.get('msg')}" for e in exc.errors()]
        raise HttpError(400, "; ".join(parts) if parts else str(exc)) from exc


@router.get(
    "/{workspace_id}/job-assignments/",
    response={
        200: list[JobAssignmentResponse],
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def list_job_assignments(request, workspace_id: int):
    workspace = _workspace_for_member(request, workspace_id)
    rows = JobAssignment.objects.filter(workspace=workspace).order_by("role_name")
    return 200, [_job_assignment_response(r) for r in rows]


@router.post(
    "/{workspace_id}/job-assignments/",
    response={
        201: JobAssignmentResponse,
        400: ErrorResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def create_job_assignment(request, workspace_id: int, data: JobAssignmentCreateRequest):
    from core.models import CyberIdentity

    workspace = _workspace_for_member(request, workspace_id)
    role_name = (data.role_name or "").strip()
    if not role_name:
        return 400, ErrorResponseSchema(error="role_name is required.", error_code="ROLE_NAME_REQUIRED")

    identity = None
    if data.identity_id is not None:
        identity = CyberIdentity.objects.filter(id=data.identity_id, workspace=workspace).first()
        if identity is None:
            return 400, ErrorResponseSchema(error="identity_id not found in this workspace.", error_code="IDENTITY_NOT_FOUND")

    raw_cfg = dict(data.config or {})
    cfg_model = _parse_job_config(raw_cfg)
    if "triggers" not in raw_cfg:
        append_default_event_triggers_if_empty(cfg_model)
    validate_job_assignment_config(
        workspace=workspace, config=cfg_model, exclude_job_assignment_id=None
    )

    row = JobAssignment(
        workspace=workspace,
        role_name=role_name[:200],
        description=(data.description or "").strip(),
        instructions=(data.instructions or "").strip(),
        enabled=data.enabled,
        identity=identity,
    )
    row.set_config(cfg_model)
    row.save()
    return 201, _job_assignment_response(row)


@router.get(
    "/{workspace_id}/job-assignments/{job_assignment_id}/",
    response={
        200: JobAssignmentResponse,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def get_job_assignment(request, workspace_id: int, job_assignment_id: uuid.UUID):
    workspace = _workspace_for_member(request, workspace_id)
    row = JobAssignment.objects.filter(id=job_assignment_id, workspace=workspace).first()
    if row is None:
        raise HttpError(404, "Job assignment not found.")
    return 200, _job_assignment_response(row)


@router.patch(
    "/{workspace_id}/job-assignments/{job_assignment_id}/",
    response={
        200: JobAssignmentResponse,
        400: ErrorResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def update_job_assignment(
    request,
    workspace_id: int,
    job_assignment_id: uuid.UUID,
    data: JobAssignmentUpdateRequest,
):
    from core.models import CyberIdentity

    workspace = _workspace_for_member(request, workspace_id)
    row = JobAssignment.objects.filter(id=job_assignment_id, workspace=workspace).first()
    if row is None:
        raise HttpError(404, "Job assignment not found.")

    if data.role_name is not None:
        name = data.role_name.strip()
        if not name:
            return 400, ErrorResponseSchema(error="role_name cannot be empty.", error_code="ROLE_NAME_REQUIRED")
        row.role_name = name[:200]
    if data.description is not None:
        row.description = data.description.strip()
    if data.instructions is not None:
        row.instructions = data.instructions.strip()
    if data.enabled is not None:
        row.enabled = data.enabled
    if "identity_id" in data.model_fields_set:
        if data.identity_id is None:
            row.identity = None
        else:
            identity = CyberIdentity.objects.filter(id=data.identity_id, workspace=workspace).first()
            if identity is None:
                return 400, ErrorResponseSchema(error="identity_id not found in this workspace.", error_code="IDENTITY_NOT_FOUND")
            row.identity = identity
    if data.config is not None:
        cfg_model = _parse_job_config({**(row.config or {}), **data.config})
        validate_job_assignment_config(
            workspace=workspace,
            config=cfg_model,
            exclude_job_assignment_id=job_assignment_id,
        )
        row.set_config(cfg_model)
    elif data.enabled is True:
        assert_unique_inbound_event_listeners(
            workspace=workspace,
            config=row.get_config(),
            exclude_job_assignment_id=job_assignment_id,
        )
    row.save()
    return 200, _job_assignment_response(row)


@router.delete(
    "/{workspace_id}/job-assignments/{job_assignment_id}/",
    response={204: None, 401: ErrorResponseSchema, 403: ErrorResponseSchema, 404: ErrorResponseSchema},
    auth=[ApiKeyAuth(), django_auth],
)
def delete_job_assignment(request, workspace_id: int, job_assignment_id: uuid.UUID):
    workspace = _workspace_for_member(request, workspace_id)
    row = JobAssignment.objects.filter(id=job_assignment_id, workspace=workspace).first()
    if row is None:
        raise HttpError(404, "Job assignment not found.")
    row.delete()
    return 204, None
