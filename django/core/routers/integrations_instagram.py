"""Instagram integration endpoints: OAuth flow, webhook (verify + receive), disconnect."""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from django.http import HttpRequest, HttpResponse
from ninja import Query, Router, Schema
from ninja.errors import HttpError
from ninja.security import django_auth

from core.models import IntegrationAccount, Workspace, WorkspaceMember
from core.schemas.integration_account import (
    InstagramAuthMethod,
    IntegrationAccountOnboarding,
)
from core.services.auth import ApiKeyAuth, auth_service
from core.services.instagram_capabilities import FACEBOOK_LOGIN_SCOPES
from core.services.instagram_facebook_login import (
    build_facebook_oauth_url,
    consume_pages_pending,
    facebook_exchange_code,
    facebook_exchange_page_token_long_lived,
    facebook_get_long_lived_token,
    facebook_get_user_pages,
    get_pages_pending,
    page_option_from_row,
    pages_with_instagram,
    resolve_page_from_pending,
    store_pages_pending,
)
from core.services.instagram_service import (
    _frontend_url,
    build_instagram_oauth_url,
    connect_instagram_account,
    consume_oauth_state,
    disconnect_instagram_account,
    handle_webhook_verification,
    instagram_exchange_code,
    instagram_get_long_lived_token,
    instagram_get_user_info,
    process_webhook_request,
    store_oauth_state,
)
from core.services.integration_account_onboarding import require_cyber_identity_in_workspace
from core.utils.schemas import ErrorResponseSchema

logger = logging.getLogger(__name__)

router = Router(tags=["Integrations / Instagram"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class InstagramOAuthUrlResponse(Schema):
    oauth_url: str


class InstagramOAuthInitRequest(Schema):
    cyber_identity_id: uuid.UUID
    use_case: str
    auth_method: Literal["instagram_login", "facebook_login"] = "instagram_login"


class InstagramConnectedAccount(Schema):
    integration_account_id: uuid.UUID
    display_name: str
    ig_username: str


class InstagramConnectResponse(Schema):
    accounts: list[InstagramConnectedAccount]


class FacebookPageOption(Schema):
    page_id: str
    page_name: str
    ig_user_id: str
    ig_username: str
    display_label: str


class FacebookPagesPendingResponse(Schema):
    workspace_id: int
    pages: list[FacebookPageOption]


class FacebookPageCompleteRequest(Schema):
    pending: str
    page_id: str


class FacebookPageCompleteResponse(Schema):
    integration_account_id: uuid.UUID
    display_name: str


# ---------------------------------------------------------------------------
# Workspace guard
# ---------------------------------------------------------------------------

def _require_workspace(request: HttpRequest, workspace_id: int) -> Workspace:
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


def _onboarding_from_state(state_payload: dict[str, object]) -> IntegrationAccountOnboarding:
    return IntegrationAccountOnboarding(
        cyber_identity_id=uuid.UUID(str(state_payload["cyber_identity_id"])),
        use_case=str(state_payload["use_case"]),
    )


def _connect_redirect_success(frontend: str, workspace_id: int, account_id: uuid.UUID) -> HttpResponse:
    return HttpResponse(
        status=302,
        headers={
            "Location": (
                f"{frontend}/workspaces/{workspace_id}/integrations"
                f"?instagram_connected=true&account_ids={account_id}"
            )
        },
    )


def _connect_integration_url(frontend: str, workspace_id: int | None, *, error: str | None = None) -> str:
    if workspace_id is None:
        base = f"{frontend}/workspace"
    else:
        base = f"{frontend}/workspaces/{workspace_id}/connect-integration"
    if error:
        return f"{base}?instagram_error={error}"
    return base


def _connect_redirect_error(frontend: str, workspace_id: int | None, reason: str) -> HttpResponse:
    if workspace_id is None:
        path = _connect_integration_url(frontend, None, error=reason)
    else:
        path = f"{frontend}/workspaces/{workspace_id}/integrations?instagram_error={reason}"
    return HttpResponse(status=302, headers={"Location": path})


def _connect_facebook_page(
    *,
    workspace: Workspace,
    user,
    onboarding: IntegrationAccountOnboarding,
    page_row: dict[str, str],
    page_access_token: str,
) -> IntegrationAccount:
    long_lived = facebook_exchange_page_token_long_lived(page_access_token)
    token = str(long_lived.get("access_token") or page_access_token)
    ig_user_id = str(page_row.get("ig_user_id") or "")
    ig_username = str(page_row.get("ig_username") or "")
    return connect_instagram_account(
        workspace=workspace,
        user=user,
        access_token=token,
        ig_user_id=ig_user_id,
        ig_username=ig_username,
        onboarding=onboarding,
        auth_method=InstagramAuthMethod.FACEBOOK_LOGIN,
        facebook_page_id=str(page_row.get("page_id") or ""),
        facebook_page_name=str(page_row.get("page_name") or ""),
        granted_scopes=list(FACEBOOK_LOGIN_SCOPES),
    )


# ---------------------------------------------------------------------------
# OAuth: initiate
# ---------------------------------------------------------------------------

@router.post(
    "/workspaces/{workspace_id}/instagram/oauth-url",
    response={
        200: InstagramOAuthUrlResponse,
        400: ErrorResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def instagram_oauth_url(request: HttpRequest, workspace_id: int, body: InstagramOAuthInitRequest):
    workspace = _require_workspace(request, workspace_id)
    user = auth_service.get_user_from_request(request)
    org = auth_service.get_active_organization(request)
    try:
        require_cyber_identity_in_workspace(
            workspace_id=workspace.id,
            cyber_identity_id=body.cyber_identity_id,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    state_token = store_oauth_state(
        workspace_id=workspace.id,
        user_id=user.pk,
        cyber_identity_id=str(body.cyber_identity_id),
        use_case=body.use_case,
        auth_method=body.auth_method,
    )
    if body.auth_method == "facebook_login":
        from django.conf import settings as django_settings

        fb_app_id = str(getattr(django_settings, "FACEBOOK_APP_ID", "") or "").strip()
        ig_app_id = str(getattr(django_settings, "INSTAGRAM_APP_ID", "") or "").strip()
        if not fb_app_id.isdigit():
            raise HttpError(
                400,
                "FACEBOOK_APP_ID is not configured. Set it in .env to the App ID from "
                "Meta App Dashboard → App settings → Basic (not the Instagram app ID).",
            )
        if ig_app_id and fb_app_id == ig_app_id:
            logger.info(
                "instagram oauth_url facebook_login using same id as INSTAGRAM_APP_ID; "
                "if Facebook Login fails, use separate App ID from Settings → Basic",
            )
        url = build_facebook_oauth_url(state_token)
    else:
        url = build_instagram_oauth_url(state_token)
    logger.info(
        "instagram oauth_url workspace_id=%s user_id=%s org_id=%s auth_method=%s",
        workspace.id,
        user.pk,
        getattr(org, "id", None),
        body.auth_method,
    )
    return 200, InstagramOAuthUrlResponse(oauth_url=url)


# ---------------------------------------------------------------------------
# OAuth: Instagram Login callback
# ---------------------------------------------------------------------------

class _CallbackParams(Schema):
    code: str | None = None
    state: str | None = None
    error: str | None = None
    error_description: str | None = None


@router.get("/callback/")
def instagram_callback(request: HttpRequest, params: _CallbackParams = Query(...)) -> HttpResponse:
    """Meta redirects here after Instagram Business Login authorization."""
    frontend = _frontend_url()

    if params.error or not params.code or not params.state:
        reason = params.error_description or params.error or "missing_code"
        logger.warning(
            "instagram_callback early_redirect reason=%s meta_error=%s",
            reason,
            params.error,
        )
        return HttpResponse(
            status=302,
            headers={"Location": _connect_integration_url(frontend, None, error=reason)},
        )

    state_payload = consume_oauth_state(params.state)
    if state_payload is None:
        return HttpResponse(
            status=302,
            headers={"Location": _connect_integration_url(frontend, None, error="invalid_state")},
        )

    auth_method = str(state_payload.get("auth_method") or InstagramAuthMethod.INSTAGRAM_LOGIN.value)
    workspace_id: int = state_payload["workspace_id"]
    user_id: int = state_payload["user_id"]
    if auth_method == InstagramAuthMethod.FACEBOOK_LOGIN.value:
        return HttpResponse(
            status=302,
            headers={
                "Location": _connect_integration_url(frontend, workspace_id, error="wrong_callback")
            },
        )

    try:
        onboarding = _onboarding_from_state(state_payload)
    except (KeyError, TypeError, ValueError):
        return HttpResponse(
            status=302,
            headers={
                "Location": _connect_integration_url(frontend, workspace_id, error="invalid_state")
            },
        )

    try:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.get(pk=user_id)
        workspace = Workspace.objects.get(id=workspace_id)

        short = instagram_exchange_code(params.code)
        long_lived = instagram_get_long_lived_token(short["access_token"])
        token = long_lived["access_token"]
        user_info = instagram_get_user_info(token)
        me_graph = str(user_info.get("id") or "").strip()
        professional = str(user_info.get("user_id") or "").strip()
        from_short = str(short.get("user_id") or "").strip()
        ig_user_id = professional or me_graph or from_short
        ig_oauth_graph_me_id = me_graph if me_graph and me_graph != ig_user_id else None
        ig_username = str(user_info.get("username") or "")
        if not ig_user_id:
            return _connect_redirect_error(frontend, workspace_id, "no_ig_accounts")

        account = connect_instagram_account(
            workspace=workspace,
            user=user,
            access_token=token,
            ig_user_id=ig_user_id,
            ig_username=ig_username,
            ig_oauth_graph_me_id=ig_oauth_graph_me_id,
            onboarding=onboarding,
            auth_method=InstagramAuthMethod.INSTAGRAM_LOGIN,
        )
        return _connect_redirect_success(frontend, workspace_id, account.id)

    except Exception:
        logger.exception("instagram_callback failed workspace_id=%s user_id=%s", workspace_id, user_id)
        return _connect_redirect_error(frontend, workspace_id, "server_error")


# ---------------------------------------------------------------------------
# OAuth: Facebook Login callback
# ---------------------------------------------------------------------------

@router.get("/facebook/callback/")
def facebook_callback(request: HttpRequest, params: _CallbackParams = Query(...)) -> HttpResponse:
    """Meta redirects here after Facebook Login for Business authorization."""
    frontend = _frontend_url()

    if params.error or not params.code or not params.state:
        reason = params.error_description or params.error or "missing_code"
        return HttpResponse(
            status=302,
            headers={"Location": _connect_integration_url(frontend, None, error=reason)},
        )

    state_payload = consume_oauth_state(params.state)
    if state_payload is None:
        return HttpResponse(
            status=302,
            headers={"Location": _connect_integration_url(frontend, None, error="invalid_state")},
        )

    auth_method = str(state_payload.get("auth_method") or "")
    workspace_id: int = state_payload["workspace_id"]
    user_id: int = state_payload["user_id"]
    if auth_method != InstagramAuthMethod.FACEBOOK_LOGIN.value:
        return HttpResponse(
            status=302,
            headers={
                "Location": _connect_integration_url(frontend, workspace_id, error="wrong_callback")
            },
        )

    try:
        onboarding = _onboarding_from_state(state_payload)
    except (KeyError, TypeError, ValueError):
        return HttpResponse(
            status=302,
            headers={
                "Location": _connect_integration_url(frontend, workspace_id, error="invalid_state")
            },
        )

    try:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.get(pk=user_id)
        workspace = Workspace.objects.get(id=workspace_id)

        short = facebook_exchange_code(params.code)
        long_lived_user = facebook_get_long_lived_token(short["access_token"])
        user_token = str(long_lived_user.get("access_token") or short["access_token"])
        all_pages = facebook_get_user_pages(user_token)
        ig_pages = pages_with_instagram(all_pages)

        if not ig_pages:
            return _connect_redirect_error(frontend, workspace_id, "no_ig_accounts")

        if len(ig_pages) == 1:
            page = ig_pages[0]
            row = page_option_from_row(page)
            page_token = str(page.get("access_token") or "")
            account = _connect_facebook_page(
                workspace=workspace,
                user=user,
                onboarding=onboarding,
                page_row=row,
                page_access_token=page_token,
            )
            return _connect_redirect_success(frontend, workspace_id, account.id)

        pending = store_pages_pending(
            workspace_id=workspace_id,
            user_id=user_id,
            onboarding=onboarding,
            pages=all_pages,
            user_access_token=user_token,
        )
        return HttpResponse(
            status=302,
            headers={
                "Location": (
                    f"{frontend}/workspaces/{workspace_id}/connect-integration/instagram-pages"
                    f"?pending={pending}"
                )
            },
        )

    except Exception:
        logger.exception("facebook_callback failed workspace_id=%s user_id=%s", workspace_id, user_id)
        return _connect_redirect_error(frontend, workspace_id, "server_error")


# ---------------------------------------------------------------------------
# Facebook Login: page picker
# ---------------------------------------------------------------------------

@router.get(
    "/workspaces/{workspace_id}/instagram/facebook-pages",
    response={
        200: FacebookPagesPendingResponse,
        400: ErrorResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def list_facebook_pages_pending(
    request: HttpRequest,
    workspace_id: int,
    pending: str = Query(...),
):
    workspace = _require_workspace(request, workspace_id)
    user = auth_service.get_user_from_request(request)
    payload = get_pages_pending(pending)
    if payload is None:
        raise HttpError(400, "Pending page selection expired or invalid.")
    if int(payload["workspace_id"]) != workspace.id or int(payload["user_id"]) != user.pk:
        raise HttpError(403, "Pending selection does not belong to this session.")
    pages_raw = payload.get("pages")
    if not isinstance(pages_raw, list):
        raise HttpError(400, "No pages in pending selection.")
    pages = [FacebookPageOption(**row) for row in pages_raw if isinstance(row, dict)]
    return 200, FacebookPagesPendingResponse(workspace_id=workspace.id, pages=pages)


@router.post(
    "/workspaces/{workspace_id}/instagram/facebook-pages/complete",
    response={
        200: FacebookPageCompleteResponse,
        400: ErrorResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
    auth=[ApiKeyAuth(), django_auth],
)
def complete_facebook_page_selection(
    request: HttpRequest,
    workspace_id: int,
    body: FacebookPageCompleteRequest,
):
    workspace = _require_workspace(request, workspace_id)
    user = auth_service.get_user_from_request(request)
    payload = consume_pages_pending(body.pending)
    if payload is None:
        raise HttpError(400, "Pending page selection expired or invalid.")
    if int(payload["workspace_id"]) != workspace.id or int(payload["user_id"]) != user.pk:
        raise HttpError(403, "Pending selection does not belong to this session.")
    try:
        onboarding = IntegrationAccountOnboarding.model_validate(payload["onboarding"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HttpError(400, "Invalid onboarding in pending selection.") from exc
    resolved = resolve_page_from_pending(payload, body.page_id)
    if resolved is None:
        raise HttpError(400, "Selected page not found in pending selection.")
    page_row, page_token = resolved
    account = _connect_facebook_page(
        workspace=workspace,
        user=user,
        onboarding=onboarding,
        page_row=page_row,
        page_access_token=page_token,
    )
    return 200, FacebookPageCompleteResponse(
        integration_account_id=account.id,
        display_name=account.display_name,
    )


# ---------------------------------------------------------------------------
# Webhook: Meta verification (GET) + events (POST)
# ---------------------------------------------------------------------------

@router.get("/webhook/")
def instagram_webhook_verify(
    request: HttpRequest,
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
) -> HttpResponse:
    status, body = handle_webhook_verification(
        hub_mode=hub_mode or "",
        hub_verify_token=hub_verify_token or "",
        hub_challenge=hub_challenge or "",
    )
    return HttpResponse(body, status=status, content_type="text/plain")


@router.post("/webhook/")
def instagram_webhook(request: HttpRequest) -> HttpResponse:
    status, body = process_webhook_request(request)
    if status != 200:
        logger.warning("instagram webhook POST status=%s", status)
    return HttpResponse(body, status=status, content_type="text/plain")


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------

@router.delete(
    "/workspaces/{workspace_id}/instagram/{integration_account_id}",
    response={204: None, 401: ErrorResponseSchema, 403: ErrorResponseSchema, 404: ErrorResponseSchema},
    auth=[ApiKeyAuth(), django_auth],
)
def instagram_disconnect(request: HttpRequest, workspace_id: int, integration_account_id: uuid.UUID):
    workspace = _require_workspace(request, workspace_id)
    user = auth_service.get_user_from_request(request)
    account = IntegrationAccount.objects.filter(
        id=integration_account_id,
        workspace=workspace,
        provider=IntegrationAccount.Provider.INSTAGRAM,
    ).first()
    if account is None:
        logger.warning(
            "instagram_disconnect not_found workspace_id=%s integration_account_id=%s user_id=%s",
            workspace_id,
            integration_account_id,
            getattr(user, "pk", None),
        )
        raise HttpError(404, "Instagram integration not found in this workspace.")
    try:
        disconnect_instagram_account(account)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return 204, None
