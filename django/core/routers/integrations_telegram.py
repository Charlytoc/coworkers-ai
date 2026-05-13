import uuid

from django.http import HttpRequest, HttpResponse
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from core.models import IntegrationAccount, Workspace, WorkspaceMember
from core.schemas.integration_account import IntegrationAccountOnboarding
from core.services.auth import ApiKeyAuth, auth_service
from core.services.integration_account_onboarding import require_cyber_identity_in_workspace
from core.services.telegram_bot import (
    approve_sender_code,
    connect_telegram_bot,
    disconnect_telegram_bot,
    process_webhook_request,
)
from core.utils.schemas import ErrorResponseSchema

router = Router(tags=["Integrations / Telegram"])


class TelegramConnectRequest(Schema):
    bot_token: str
    display_name: str | None = None
    cyber_identity_id: uuid.UUID
    use_case: str


class TelegramConnectResponse(Schema):
    integration_account_id: uuid.UUID
    display_name: str


class TelegramApproveRequest(Schema):
    integration_account_id: uuid.UUID
    code: str


class TelegramApproveResponse(Schema):
    approved_telegram_user_id: str


def _require_workspace(request, workspace_id: int) -> Workspace:
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


@router.post("/webhook/{webhook_path_token}/")
def telegram_webhook(request: HttpRequest, webhook_path_token: str) -> HttpResponse:
    status, body = process_webhook_request(request, webhook_path_token)
    return HttpResponse(body, status=status, content_type="text/plain")


@router.post(
    "/workspaces/{workspace_id}/telegram/connect",
    response={
        201: TelegramConnectResponse,
        400: ErrorResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def telegram_connect(request, workspace_id: int, data: TelegramConnectRequest):
    workspace = _require_workspace(request, workspace_id)
    user = auth_service.get_user_from_request(request)
    try:
        require_cyber_identity_in_workspace(
            workspace_id=workspace.id,
            cyber_identity_id=data.cyber_identity_id,
        )
        onboarding = IntegrationAccountOnboarding(
            cyber_identity_id=data.cyber_identity_id,
            use_case=data.use_case,
        )
        account = connect_telegram_bot(
            workspace=workspace,
            user=user,
            bot_token=data.bot_token,
            display_name=data.display_name,
            onboarding=onboarding,
        )
    except ValueError as exc:
        return 400, ErrorResponseSchema(error=str(exc), error_code="telegram_connect_failed")
    return 201, TelegramConnectResponse(
        integration_account_id=account.id,
        display_name=account.display_name or "",
    )


@router.post(
    "/workspaces/{workspace_id}/telegram/approve-sender",
    response={
        200: TelegramApproveResponse,
        400: ErrorResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def telegram_approve_sender(request, workspace_id: int, data: TelegramApproveRequest):
    workspace = _require_workspace(request, workspace_id)
    account = IntegrationAccount.objects.filter(
        id=data.integration_account_id,
        workspace=workspace,
        provider=IntegrationAccount.Provider.TELEGRAM,
    ).first()
    if account is None:
        raise HttpError(404, "Telegram integration not found in this workspace.")
    try:
        uid = approve_sender_code(account=account, code=data.code)
    except ValueError as exc:
        return 400, ErrorResponseSchema(error=str(exc), error_code="telegram_approve_failed")
    return 200, TelegramApproveResponse(approved_telegram_user_id=uid)


@router.delete(
    "/workspaces/{workspace_id}/telegram/{integration_account_id}",
    response={204: None, 401: ErrorResponseSchema, 403: ErrorResponseSchema, 404: ErrorResponseSchema},
    auth=[ApiKeyAuth(), django_auth],
)
def telegram_disconnect(request, workspace_id: int, integration_account_id: uuid.UUID):
    workspace = _require_workspace(request, workspace_id)
    account = IntegrationAccount.objects.filter(
        id=integration_account_id,
        workspace=workspace,
        provider=IntegrationAccount.Provider.TELEGRAM,
    ).first()
    if account is None:
        raise HttpError(404, "Telegram integration not found in this workspace.")
    try:
        disconnect_telegram_bot(account)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return 204, None
