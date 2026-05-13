"""Instagram Business Login API helpers, OAuth flow, webhook handling, and IntegrationAccount conventions.

Uses the new Instagram Business Login (instagram.com/oauth/authorize) introduced in 2024,
NOT the deprecated Facebook Login / facebook.com/dialog/oauth path.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from typing import Any
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import HttpRequest

from core.integrations.event_types import INSTAGRAM_DM_MESSAGE
from core.models import IntegrationAccount, IntegrationEvent, Workspace
from core.schemas.integration_account import (
    INTEGRATION_ONBOARDING_CONFIG_KEY,
    IntegrationAccountOnboarding,
)

logger = logging.getLogger(__name__)

# Instagram Business Login endpoints
INSTAGRAM_OAUTH_URL = "https://www.instagram.com/oauth/authorize"
INSTAGRAM_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
INSTAGRAM_GRAPH_BASE = "https://graph.instagram.com"
INSTAGRAM_GRAPH_API_VERSION = "v25.0"

# Keys in IntegrationAccount.auth (encrypted)
AUTH_ACCESS_TOKEN = "access_token"

# Keys in IntegrationAccount.config (plaintext JSON)
CONFIG_IG_USER_ID = "ig_user_id"
CONFIG_IG_USERNAME = "ig_username"
CONFIG_IG_OAUTH_GRAPH_ME_ID = "ig_oauth_graph_me_id"

# Redis cache key for OAuth state
_OAUTH_STATE_TTL = 600  # 10 minutes
_OAUTH_STATE_PREFIX = "ig_oauth_state:"

# Scopes for Instagram Business Login
INSTAGRAM_OAUTH_SCOPES = [
    "instagram_business_basic",
    "instagram_business_manage_messages",
    "instagram_business_content_publish",
]


def _oauth_response_for_log(data: dict[str, Any]) -> dict[str, Any]:
    """Omit secrets from token endpoint JSON for logging."""
    out: dict[str, Any] = {}
    for key, val in data.items():
        if key == "access_token":
            s = str(val) if val is not None else ""
            out[key] = f"<set len={len(s)}>" if s else "<empty>"
        else:
            out[key] = val
    return out


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def _app_id() -> str:
    return str(getattr(settings, "INSTAGRAM_APP_ID", "") or "")


def _app_secret() -> str:
    return str(getattr(settings, "INSTAGRAM_APP_SECRET", "") or "")


def _frontend_url() -> str:
    return str(getattr(settings, "FRONTEND_URL", "http://localhost:3000")).rstrip("/")


def _callback_url() -> str:
    base = str(getattr(settings, "SITE_URL", "http://127.0.0.1:8000")).rstrip("/")
    return f"{base}/api/integrations/instagram/callback/"


# ---------------------------------------------------------------------------
# OAuth state (Redis cache)
# ---------------------------------------------------------------------------


def _state_cache_key(state_token: str) -> str:
    return f"{_OAUTH_STATE_PREFIX}{state_token}"


def store_oauth_state(
    *,
    workspace_id: int,
    user_id: int,
    cyber_identity_id: str,
    use_case: str,
) -> str:
    """Generate a random state token, store workspace/user/onboarding in cache, return the token."""
    token = secrets.token_urlsafe(32)
    cache.set(
        _state_cache_key(token),
        {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "cyber_identity_id": cyber_identity_id,
            "use_case": use_case,
        },
        _OAUTH_STATE_TTL,
    )
    return token


def consume_oauth_state(state_token: str) -> dict[str, object] | None:
    """Retrieve and delete the OAuth state payload. Returns None if missing/expired."""
    key = _state_cache_key(state_token)
    payload = cache.get(key)
    if payload is None:
        logger.warning(
            "instagram_oauth_state consume miss state_prefix=%s",
            (state_token[:10] + "…") if state_token else "(empty)",
        )
        return None
    cache.delete(key)
    return payload


# ---------------------------------------------------------------------------
# OAuth URL builder
# ---------------------------------------------------------------------------


def build_instagram_oauth_url(state_token: str) -> str:
    redirect_uri = _callback_url()
    app_id = _app_id()
    params = {
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": ",".join(INSTAGRAM_OAUTH_SCOPES),
        "response_type": "code",
        "state": state_token,
    }
    return f"{INSTAGRAM_OAUTH_URL}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Token exchange (Instagram Business Login)
# ---------------------------------------------------------------------------


def instagram_exchange_code(code: str) -> dict[str, Any]:
    """Exchange authorization code for a short-lived Instagram user access token."""
    resp = requests.post(
        INSTAGRAM_TOKEN_URL,
        data={
            "client_id": _app_id(),
            "client_secret": _app_secret(),
            "grant_type": "authorization_code",
            "redirect_uri": _callback_url(),
            "code": code,
        },
        timeout=20,
    )
    data = resp.json()
    if "error_type" in data or "error" in data:
        msg = (
            data.get("error_message")
            or data.get("error", {}).get("message")
            or "Code exchange failed"
        )
        logger.warning(
            "instagram oauth exchange error=%s",
            _oauth_response_for_log(data) if isinstance(data, dict) else data,
        )
        raise ValueError(msg)
    return data


def instagram_get_long_lived_token(short_token: str) -> dict[str, Any]:
    """Exchange a short-lived token for a long-lived Instagram user token (60 days)."""
    url = f"{INSTAGRAM_GRAPH_BASE}/access_token"
    resp = requests.get(
        url,
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": _app_secret(),
            "access_token": short_token,
        },
        timeout=20,
    )
    data = resp.json()
    if "error" in data:
        logger.warning("instagram long_lived_token error=%s", data.get("error"))
        raise ValueError(
            data["error"].get("message", "Long-lived token exchange failed")
        )
    return data


# ---------------------------------------------------------------------------
# Graph API: user info
# ---------------------------------------------------------------------------


def instagram_get_user_info(access_token: str) -> dict[str, Any]:
    """Fetch IG profile fields for the authenticated user.

    ``user_id`` (when present) is the Instagram professional account id used in webhooks
    (``entry.id``); ``id`` can differ and historically matched only parts of the Graph API.
    """
    url = f"{INSTAGRAM_GRAPH_BASE}/me"
    me_fields = "id,username,name,user_id,account_type"
    resp = requests.get(
        url,
        params={
            "fields": me_fields,
            "access_token": access_token,
        },
        timeout=20,
    )
    data = resp.json()
    if "error" in data:
        logger.warning("instagram /me error=%s", data.get("error"))
        raise ValueError(data["error"].get("message", "Failed to fetch user info"))
    return data


# ---------------------------------------------------------------------------
# Graph API: send DM
# ---------------------------------------------------------------------------


def instagram_send_message(
    access_token: str, ig_user_id: str, recipient_igsid: str, text: str
) -> dict[str, Any]:
    """Send a text DM from the IG Business Account to recipient_igsid."""
    resp = requests.post(
        f"{INSTAGRAM_GRAPH_BASE}/{INSTAGRAM_GRAPH_API_VERSION}/{ig_user_id}/messages",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "recipient": {"id": recipient_igsid},
            "message": {"text": text},
        },
        timeout=20,
    )
    data = resp.json()
    if "error" in data:
        raise ValueError(data["error"].get("message", "Instagram sendMessage failed"))
    return data


# ---------------------------------------------------------------------------
# Graph API: content publishing
# ---------------------------------------------------------------------------


def _instagram_graph_error_message(data: dict[str, Any], fallback: str) -> str:
    error = data.get("error")
    if not isinstance(error, dict):
        return fallback
    message = str(error.get("message") or fallback)
    code = error.get("code")
    subcode = error.get("error_subcode")
    details = []
    if code is not None:
        details.append(f"code={code}")
    if subcode is not None:
        details.append(f"subcode={subcode}")
    if details:
        return f"{message} ({', '.join(details)})"
    return message


def instagram_create_image_media_container(
    *,
    access_token: str,
    ig_user_id: str,
    image_url: str,
    caption: str = "",
) -> dict[str, Any]:
    uid = str(ig_user_id or "").strip()
    url = str(image_url or "").strip()
    if not access_token or not uid:
        raise ValueError("Instagram token or ig_user_id not configured")
    if not url:
        raise ValueError("image_url is required")
    payload = {
        "image_url": url,
        "media_type": "IMAGE",
        "access_token": access_token,
    }
    if caption.strip():
        payload["caption"] = caption.strip()
    endpoint = f"{INSTAGRAM_GRAPH_BASE}/{INSTAGRAM_GRAPH_API_VERSION}/{uid}/media"
    logger.info(
        "instagram media container request ig_user_id=%s media_type=IMAGE "
        "caption_len=%s image_url=%s endpoint=%s",
        uid,
        len(caption.strip()),
        url,
        endpoint,
    )
    resp = requests.post(
        endpoint,
        data=payload,
        timeout=60,
    )
    try:
        data = resp.json()
    except ValueError as exc:
        logger.warning(
            "instagram media container invalid_json status=%s body_preview=%r",
            resp.status_code,
            resp.text[:1000],
        )
        raise ValueError("Instagram media container returned invalid JSON") from exc
    if resp.status_code >= 400:
        logger.warning(
            "instagram media container failed status=%s image_url=%s response=%s",
            resp.status_code,
            url,
            data,
        )
    else:
        logger.info(
            "instagram media container response status=%s container_id=%s image_url=%s",
            resp.status_code,
            data.get("id"),
            url,
        )
    if "error" in data:
        raise ValueError(_instagram_graph_error_message(data, "Instagram media container failed"))
    if not data.get("id"):
        raise ValueError("Instagram media container returned no id")
    return data


def instagram_publish_media_container(
    *,
    access_token: str,
    ig_user_id: str,
    creation_id: str,
) -> dict[str, Any]:
    uid = str(ig_user_id or "").strip()
    cid = str(creation_id or "").strip()
    if not access_token or not uid:
        raise ValueError("Instagram token or ig_user_id not configured")
    if not cid:
        raise ValueError("creation_id is required")
    endpoint = f"{INSTAGRAM_GRAPH_BASE}/{INSTAGRAM_GRAPH_API_VERSION}/{uid}/media_publish"
    logger.info(
        "instagram media publish request ig_user_id=%s creation_id=%s endpoint=%s",
        uid,
        cid,
        endpoint,
    )
    resp = requests.post(
        endpoint,
        data={"creation_id": cid, "access_token": access_token},
        timeout=60,
    )
    try:
        data = resp.json()
    except ValueError as exc:
        logger.warning(
            "instagram media publish invalid_json status=%s body_preview=%r",
            resp.status_code,
            resp.text[:1000],
        )
        raise ValueError("Instagram media publish returned invalid JSON") from exc
    if resp.status_code >= 400:
        logger.warning(
            "instagram media publish failed status=%s creation_id=%s response=%s",
            resp.status_code,
            cid,
            data,
        )
    else:
        logger.info(
            "instagram media publish response status=%s published_id=%s creation_id=%s",
            resp.status_code,
            data.get("id"),
            cid,
        )
    if "error" in data:
        raise ValueError(_instagram_graph_error_message(data, "Instagram media publish failed"))
    if not data.get("id"):
        raise ValueError("Instagram media publish returned no id")
    return data


def instagram_publish_image_post(
    *,
    access_token: str,
    ig_user_id: str,
    image_url: str,
    caption: str = "",
) -> dict[str, Any]:
    container = instagram_create_image_media_container(
        access_token=access_token,
        ig_user_id=ig_user_id,
        image_url=image_url,
        caption=caption,
    )
    published = instagram_publish_media_container(
        access_token=access_token,
        ig_user_id=ig_user_id,
        creation_id=str(container["id"]),
    )
    return {"container": container, "published": published}


# ---------------------------------------------------------------------------
# Graph API: Webhook field subscriptions (subscribed_apps)
# ---------------------------------------------------------------------------
# https://developers.facebook.com/docs/instagram-platform/webhooks


def _instagram_webhook_subscribed_fields_csv() -> str:
    raw = getattr(settings, "INSTAGRAM_WEBHOOK_SUBSCRIBED_FIELDS", "messages")
    if isinstance(raw, (list, tuple)):
        parts = [str(x).strip() for x in raw if str(x).strip()]
        return ",".join(parts) if parts else "messages"
    s = str(raw).strip()
    return s if s else "messages"


def instagram_enable_webhook_subscriptions(
    *, access_token: str, ig_user_id: str
) -> dict[str, Any]:
    """Enable Meta→app webhook delivery for this Instagram professional account.

    Per Meta: ``POST https://graph.instagram.com/{{version}}/{{instagram-account-id}}/subscribed_apps``
    with ``subscribed_fields`` and the Instagram User access token.
    """
    uid = str(ig_user_id or "").strip()
    if not access_token or not uid:
        return {"success": False, "error": "missing_token_or_ig_user_id"}
    fields = _instagram_webhook_subscribed_fields_csv()
    url = f"{INSTAGRAM_GRAPH_BASE}/{INSTAGRAM_GRAPH_API_VERSION}/{uid}/subscribed_apps"
    resp = requests.post(
        url,
        params={"subscribed_fields": fields, "access_token": access_token},
        timeout=30,
    )
    raw_text = resp.text or ""
    try:
        data = resp.json()
    except ValueError:
        logger.warning(
            "instagram subscribed_apps POST invalid_json http_status=%s",
            resp.status_code,
        )
        return {
            "success": False,
            "http_status": resp.status_code,
            "error": "invalid_json",
        }
    if not isinstance(data, dict):
        return {
            "success": False,
            "http_status": resp.status_code,
            "error": "non_object_response",
        }
    if "error" in data:
        logger.warning(
            "instagram subscribed_apps POST graph_error http_status=%s err=%s",
            resp.status_code,
            json.dumps(data.get("error"), default=str)[:2000],
        )
        return {
            "success": False,
            "http_status": resp.status_code,
            "error": data.get("error"),
        }
    if data.get("success") is True:
        return {"success": True, "http_status": resp.status_code, "data": data}
    ok = 200 <= resp.status_code < 300
    if not ok:
        logger.warning(
            "instagram subscribed_apps POST unexpected http_status=%s",
            resp.status_code,
        )
    return {"success": ok, "http_status": resp.status_code, "data": data}


def instagram_disable_webhook_subscriptions(
    *, access_token: str, ig_user_id: str
) -> dict[str, Any]:
    """Remove this app's webhook subscription for the IG account (best-effort; same path as POST)."""
    uid = str(ig_user_id or "").strip()
    if not access_token or not uid:
        return {"success": False, "error": "missing_token_or_ig_user_id"}
    url = f"{INSTAGRAM_GRAPH_BASE}/{INSTAGRAM_GRAPH_API_VERSION}/{uid}/subscribed_apps"
    resp = requests.delete(url, params={"access_token": access_token}, timeout=30)
    try:
        data = resp.json()
    except ValueError:
        logger.warning(
            "instagram subscribed_apps DELETE invalid_json http_status=%s",
            resp.status_code,
        )
        return {
            "success": False,
            "http_status": resp.status_code,
            "error": "invalid_json",
        }
    if isinstance(data, dict) and "error" in data:
        logger.warning(
            "instagram subscribed_apps DELETE graph_error http_status=%s err=%s",
            resp.status_code,
            json.dumps(data.get("error"), default=str)[:2000],
        )
        return {
            "success": False,
            "http_status": resp.status_code,
            "error": data.get("error"),
        }
    if isinstance(data, dict) and data.get("success") is True:
        return {"success": True, "http_status": resp.status_code, "data": data}
    ok = 200 <= resp.status_code < 300
    return {
        "success": ok,
        "http_status": resp.status_code,
        "data": data if isinstance(data, dict) else {},
    }


# ---------------------------------------------------------------------------
# IntegrationAccount helpers
# ---------------------------------------------------------------------------


def get_access_token(account: IntegrationAccount) -> str:
    return str((account.auth or {}).get(AUTH_ACCESS_TOKEN, "")).strip()


def _normalize_instagram_graph_profile_payload(data: dict[str, Any]) -> dict[str, str]:
    """Pick ``username`` / ``name`` from Graph JSON into a small flat dict (bare username, no ``@``)."""
    out: dict[str, str] = {}
    raw_u = data.get("username")
    if isinstance(raw_u, str) and raw_u.strip():
        out["username"] = raw_u.strip().lstrip("@")
    raw_n = data.get("name")
    if isinstance(raw_n, str) and raw_n.strip():
        out["name"] = raw_n.strip()
    return out


def instagram_fetch_participant_profile(
    *,
    account: IntegrationAccount,
    access_token: str,
    participant_igsid: str,
) -> dict[str, str] | None:
    """Fetch DM participant fields from the Instagram User Profile API (IGSID).

    Returns a dict with zero or more of: ``username``, ``name`` (both plain strings;
    ``username`` has no ``@`` prefix). Used for ``handle`` and for ``extractions`` enrichment.

    **Instagram User Profile API** — ``GET /<INSTAGRAM_SCOPED_ID>?fields=name,username`` on
    ``graph.instagram.com`` with the Instagram user access token for the professional account
    that received the webhook.

    **User consent:** required after the user has messaged your app user's professional account
    (or certain messaging opt-ins / menus); otherwise Graph may return a consent error.

    **Permissions:** ``instagram_business_basic``, ``instagram_business_manage_messages``.

    Reference:
    https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/user-profile/
    """
    igsid = str(participant_igsid or "").strip()
    if not igsid or not access_token:
        return None
    cache_key = f"ig_participant_profile:{account.id}:{igsid}"
    cached = cache.get(cache_key)
    if isinstance(cached, str) and cached.strip():
        raw_s = cached.strip()
        try:
            parsed = json.loads(cached)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict) and parsed:
            filtered = {
                k: str(v)
                for k, v in parsed.items()
                if k in ("username", "name") and str(v).strip()
            }
            if filtered:
                return filtered
        # Legacy cache: bare username string from older ``ig_participant_username`` entries
        if not raw_s.startswith("{"):
            u = raw_s.lstrip("@")
            return {"username": u} if u else None

    url = f"{INSTAGRAM_GRAPH_BASE}/{INSTAGRAM_GRAPH_API_VERSION}/{igsid}"
    resp = requests.get(
        url,
        params={"fields": "name,username", "access_token": access_token},
        timeout=15,
    )
    try:
        data = resp.json()
    except ValueError:
        logger.warning(
            "instagram participant profile invalid_json http_status=%s igsid_prefix=%s",
            resp.status_code,
            igsid[:12],
        )
        return None
    if not isinstance(data, dict):
        return None
    if "error" in data:
        err = data.get("error")
        logger.info(
            "instagram participant profile graph_error igsid_prefix=%s err=%s",
            igsid[:12],
            json.dumps(err, default=str)[:500] if err is not None else "",
        )
        return None
    normalized = _normalize_instagram_graph_profile_payload(data)
    if not normalized:
        return None
    cache.set(cache_key, json.dumps(normalized, ensure_ascii=False), 86_400)
    return normalized


def instagram_dm_sender_handle_from_webhook_or_profile(
    messaging: dict[str, Any],
    profile: dict[str, str] | None,
) -> str | None:
    """``@username`` from webhook ``sender`` if present; else from User Profile ``profile``."""
    sender = messaging.get("sender")
    if isinstance(sender, dict):
        wu = sender.get("username")
        if isinstance(wu, str):
            u = wu.strip().lstrip("@")
            if u:
                return f"@{u}"
    if profile:
        u = profile.get("username", "").strip().lstrip("@")
        if u:
            return f"@{u}"
    return None


def get_ig_user_id(account: IntegrationAccount) -> str:
    return str(
        (account.config or {}).get(CONFIG_IG_USER_ID, account.external_account_id)
    ).strip()


def _find_account_by_ig_user_id(ig_user_id: str) -> IntegrationAccount | None:
    """Match webhook ``entry.id`` (professional id) to a connected account.

    Older rows stored only ``/me`` ``id`` on ``external_account_id``; webhooks use
    ``/me`` ``user_id``. We also match ``config.ig_oauth_graph_me_id`` for those rows
    when the webhook sends the graph ``id`` instead (rare).
    """
    if not ig_user_id:
        return None
    base = IntegrationAccount.objects.filter(
        provider=IntegrationAccount.Provider.INSTAGRAM,
        status=IntegrationAccount.Status.ACTIVE,
    )
    acc = base.filter(external_account_id=ig_user_id).first()
    if acc is not None:
        return acc
    return base.filter(config__ig_oauth_graph_me_id=ig_user_id).first()


# ---------------------------------------------------------------------------
# Connect / disconnect
# ---------------------------------------------------------------------------


def connect_instagram_account(
    *,
    workspace: Workspace,
    user,
    access_token: str,
    ig_user_id: str,
    ig_username: str,
    ig_oauth_graph_me_id: str | None = None,
    onboarding: IntegrationAccountOnboarding | None = None,
) -> IntegrationAccount:
    """Create or update an IntegrationAccount for a connected Instagram Business account."""
    uid = getattr(user, "pk", None)
    logger.info(
        "instagram connect workspace_id=%s user_id=%s ig_user_id=%s ig_username=%s",
        workspace.id,
        uid,
        ig_user_id,
        ig_username or "",
    )
    display_name = f"@{ig_username}" if ig_username else ig_user_id

    def _ig_config() -> dict[str, Any]:
        cfg: dict[str, Any] = {
            CONFIG_IG_USER_ID: ig_user_id,
            CONFIG_IG_USERNAME: ig_username,
        }
        if ig_oauth_graph_me_id and ig_oauth_graph_me_id != ig_user_id:
            cfg[CONFIG_IG_OAUTH_GRAPH_ME_ID] = ig_oauth_graph_me_id
        if onboarding is not None:
            cfg[INTEGRATION_ONBOARDING_CONFIG_KEY] = onboarding.model_dump(mode="json")
        return cfg

    with transaction.atomic():
        account, _created = IntegrationAccount.objects.get_or_create(
            workspace=workspace,
            provider=IntegrationAccount.Provider.INSTAGRAM,
            external_account_id=ig_user_id,
            defaults={
                "created_by": user if getattr(user, "pk", None) else None,
                "display_name": display_name[:200],
                "status": IntegrationAccount.Status.ACTIVE,
                "config": _ig_config(),
            },
        )
        if not _created:
            account.display_name = display_name[:200]
            account.status = IntegrationAccount.Status.ACTIVE
            cfg = dict(account.config or {})
            cfg.pop("me_accounts_snapshot", None)
            cfg[CONFIG_IG_USER_ID] = ig_user_id
            cfg[CONFIG_IG_USERNAME] = ig_username
            if ig_oauth_graph_me_id and ig_oauth_graph_me_id != ig_user_id:
                cfg[CONFIG_IG_OAUTH_GRAPH_ME_ID] = ig_oauth_graph_me_id
            elif CONFIG_IG_OAUTH_GRAPH_ME_ID in cfg and (
                not ig_oauth_graph_me_id or ig_oauth_graph_me_id == ig_user_id
            ):
                cfg.pop(CONFIG_IG_OAUTH_GRAPH_ME_ID, None)
            if onboarding is not None:
                cfg[INTEGRATION_ONBOARDING_CONFIG_KEY] = onboarding.model_dump(mode="json")
            account.config = cfg

        account.auth = {AUTH_ACCESS_TOKEN: access_token}
        account.save()

    if onboarding is not None:
        from core.tasks.integration_onboarding import provision_integration_default_job

        provision_integration_default_job.delay(str(account.id))

    logger.info(
        "instagram connect done account_id=%s workspace_id=%s created=%s external_account_id=%s",
        account.id,
        workspace.id,
        _created,
        account.external_account_id,
    )

    sub = instagram_enable_webhook_subscriptions(
        access_token=access_token, ig_user_id=ig_user_id
    )
    if not sub.get("success"):
        logger.warning(
            "instagram subscribed_apps_failed account_id=%s detail=%s",
            account.id,
            json.dumps(sub, default=str)[:2000],
        )
    else:
        logger.info("instagram subscribed_apps_ok account_id=%s", account.id)

    return account


def disconnect_instagram_account(account: IntegrationAccount) -> None:
    if account.provider != IntegrationAccount.Provider.INSTAGRAM:
        raise ValueError("not an Instagram integration")
    token = get_access_token(account)
    ig_uid = str(account.external_account_id or "").strip() or get_ig_user_id(account)
    if token and ig_uid:
        unsub = instagram_disable_webhook_subscriptions(
            access_token=token, ig_user_id=ig_uid
        )
        if not unsub.get("success"):
            logger.warning(
                "instagram subscribed_apps DELETE failed account_id=%s detail=%s",
                account.id,
                json.dumps(unsub, default=str)[:2000],
            )
        else:
            logger.info(
                "Isntagram account unsubscribed successfully account_id=%s", account.id
            )
    account.delete()


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


def verify_webhook_signature(request: HttpRequest) -> bool:
    """Validate X-Hub-Signature-256 against HMAC-SHA256(app_secret, body)."""
    secret = _app_secret()
    if not secret:
        logger.warning("instagram_webhook_signature skip app_secret not configured")
        return False
    sig_header = request.headers.get("X-Hub-Signature-256", "")
    if not sig_header:
        logger.warning(
            "instagram_webhook_signature fail missing X-Hub-Signature-256 header"
        )
        return False
    if not sig_header.startswith("sha256="):
        logger.warning(
            "instagram_webhook_signature fail bad header format has_prefix=%s",
            sig_header[:16],
        )
        return False
    expected = (
        "sha256=" + hmac.new(secret.encode(), request.body, hashlib.sha256).hexdigest()
    )
    ok = secrets.compare_digest(expected, sig_header)
    if not ok:
        logger.warning(
            "instagram_webhook_signature fail mismatch body_len=%s",
            len(request.body or b""),
        )
    return ok


def _is_instagram_messaging_edit_notification(messaging: dict[str, Any]) -> bool:
    """True when Meta is notifying about a DM edit, not a new inbound message."""
    if not isinstance(messaging, dict):
        return False
    msg = messaging.get("message")
    if isinstance(msg, dict) and msg.get("is_edit"):
        return True
    if isinstance(messaging.get("message_edit"), dict):
        return True
    return False


def _instagram_webhook_messaging_needs_dm_worker(messaging: dict[str, Any]) -> bool:
    """True only for payloads that can represent user text (skip read/delivery-only webhooks)."""
    if not isinstance(messaging, dict):
        return False
    if _is_instagram_messaging_edit_notification(messaging):
        return False
    msg = messaging.get("message")
    if isinstance(msg, dict) and msg:
        return True
    return bool(msg)


def _normalize_instagram_messaging_for_dm(
    messaging: dict[str, Any],
) -> dict[str, Any] | None:
    """Return ``messaging`` with a ``message`` object, synthesizing one from ``message_edit`` when needed.

    Instagram can deliver edits as ``message_edit`` without a parallel ``message`` webhook; see
    https://developers.facebook.com/docs/instagram-platform/webhooks/examples/

    Webhook dispatch filters out edit notifications before enqueueing the DM worker, so this
    normalization path is only reached for direct calls or pre-filter legacy payloads.
    """
    if not isinstance(messaging, dict):
        return None
    if messaging.get("message"):
        return messaging
    edit = messaging.get("message_edit")
    if not isinstance(edit, dict):
        return None
    mid = str(edit.get("mid") or "").strip()
    if not mid:
        return None
    merged = dict(messaging)
    merged["message"] = {
        "mid": mid,
        "text": str(edit.get("text") or ""),
        "is_edit": True,
        "num_edit": edit.get("num_edit"),
    }
    logger.debug(
        "instagram webhook normalized message_edit mid_prefix=%s num_edit=%s",
        mid[:32],
        edit.get("num_edit"),
    )
    return merged


def _instagram_sender_from_stored_mid(
    *, account: IntegrationAccount, mid: str
) -> str | None:
    """Recover the DM peer IGSID using a prior user ``Message`` or ``IntegrationEvent`` with the same ``mid``."""
    from core.models.conversation import Conversation
    from core.models.message import Message

    msg = (
        Message.objects.filter(
            conversation__integration_account_id=account.id,
            conversation__origin=Conversation.Origin.INTEGRATION,
            role=Message.Role.USER,
            content_structured__instagram_message__message__mid=mid,
        )
        .select_related("conversation")
        .order_by("-created")
        .first()
    )
    if msg is not None and msg.conversation_id is not None:
        try:
            tid = (msg.conversation.get_config().external_thread_id or "").strip()
        except Exception:
            tid = ""
        if tid:
            return tid

    ev = (
        IntegrationEvent.objects.filter(
            integration_account=account,
            event_type=INSTAGRAM_DM_MESSAGE.slug,
            payload__message__mid=mid,
        )
        .order_by("-received_at")
        .first()
    )
    if ev is not None and isinstance(ev.payload, dict):
        sid = str((ev.payload.get("sender") or {}).get("id") or "").strip()
        ext = str(account.external_account_id or "").strip()
        if sid and sid != ext:
            return sid
    return None


def _instagram_sender_from_single_active_thread(
    *, account: IntegrationAccount
) -> str | None:
    """If exactly one active integration thread exists, use its external thread id as the peer."""
    from core.models.conversation import Conversation

    convs = list(
        Conversation.objects.filter(
            integration_account_id=account.id,
            origin=Conversation.Origin.INTEGRATION,
            status=Conversation.Status.ACTIVE,
        )[:2]
    )
    if len(convs) != 1:
        return None
    try:
        tid = (convs[0].get_config().external_thread_id or "").strip()
    except Exception:
        tid = ""
    return tid or None


def _resolve_instagram_dm_sender_igsid(
    *,
    account: IntegrationAccount,
    messaging: dict[str, Any],
    ig_account_id: str,
    message: dict[str, Any],
) -> str:
    """Instagram-scoped id of the human in the thread (not the professional inbox id)."""
    biz = str(ig_account_id or "").strip()

    def _peer(x: str) -> bool:
        return bool(x) and x != biz

    sender = str((messaging.get("sender") or {}).get("id") or "").strip()
    # Outbound / echo: Meta sets sender to the professional inbox id and recipient to the human.
    # Never treat recipient as the "inbound user" in that case (it caused reply→webhook→reply loops).
    if sender == biz:
        return ""

    if _peer(sender):
        return sender

    recipient = str((messaging.get("recipient") or {}).get("id") or "").strip()
    if not sender and _peer(recipient):
        return recipient

    mid = str(message.get("mid") or "").strip()
    if mid and message.get("is_edit"):
        recovered = _instagram_sender_from_stored_mid(account=account, mid=mid)
        if recovered and _peer(recovered):
            logger.debug(
                "instagram_dm_sender_recovered_from_mid mid_prefix=%s sender=%s",
                mid[:24],
                recovered,
            )
            return recovered
        single = _instagram_sender_from_single_active_thread(account=account)
        if single and _peer(single):
            logger.debug(
                "instagram_dm_sender_recovered_single_thread sender=%s", single
            )
            return single

    return ""


def process_instagram_webhook_messaging(
    *,
    account: IntegrationAccount,
    ig_account_id: str,
    raw_messaging: dict[str, Any],
) -> None:
    """Worker-side: normalize payload, resolve sender, record event, run DM + agent."""
    logger.debug(
        "instagram_dm_worker keys=%s account_id=%s",
        list(raw_messaging.keys()),
        account.id,
    )
    messaging = _normalize_instagram_messaging_for_dm(dict(raw_messaging))
    if messaging is None:
        logger.info(
            "instagram_dm_worker skip cannot_normalize keys=%s account_id=%s",
            list(raw_messaging.keys()),
            account.id,
        )
        return

    message = messaging.get("message")
    if not isinstance(message, dict) or not message:
        logger.info(
            "instagram_dm_worker skip no_message account_id=%s keys=%s",
            account.id,
            list(messaging.keys()),
        )
        return
    if message.get("is_echo"):
        logger.info("instagram_dm_worker skip is_echo account_id=%s", account.id)
        return
    if message.get("is_self"):
        logger.info("instagram_dm_worker skip is_self account_id=%s", account.id)
        return
    if _is_instagram_messaging_edit_notification(messaging):
        logger.info(
            "instagram_dm_worker skip edit_notification account_id=%s", account.id
        )
        return

    sender_igsid = _resolve_instagram_dm_sender_igsid(
        account=account,
        messaging=messaging,
        ig_account_id=ig_account_id,
        message=message,
    )
    if not sender_igsid or sender_igsid == ig_account_id:
        logger.info(
            "instagram_dm_worker skip sender inbox_id=%s sender=%s is_edit=%s account_id=%s",
            ig_account_id,
            sender_igsid or "",
            bool(message.get("is_edit")),
            account.id,
        )
        return

    mid = str(message.get("mid") or "")
    logger.info(
        "instagram_dm_worker dispatch account_id=%s sender=%s is_edit=%s",
        account.id,
        sender_igsid,
        bool(message.get("is_edit")),
    )
    _record_dm_event(account, messaging)

    from core.services.instagram_events_processor import process_instagram_dm

    process_instagram_dm(
        account=account, messaging=messaging, sender_igsid=sender_igsid
    )


def _handle_webhook_payload(payload: dict[str, Any]) -> None:
    """Dispatch each messaging entry to the appropriate account's event processor."""
    obj = payload.get("object")
    if obj != "instagram":
        logger.debug("instagram webhook skip object=%r", obj)
        return

    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        logger.warning(
            "instagram webhook malformed entry type=%s", type(entries).__name__
        )
        return

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ig_account_id = str(entry.get("id") or "")
        if not ig_account_id:
            logger.warning(
                "instagram webhook entry missing id keys=%s", list(entry.keys())
            )
            continue

        messaging_list = entry.get("messaging", [])
        if not isinstance(messaging_list, list):
            messaging_list = []

        account = _find_account_by_ig_user_id(ig_account_id)
        if account is None:
            logger.warning("instagram webhook no_account inbox_id=%s", ig_account_id)
            continue

        for messaging in messaging_list:
            if not isinstance(messaging, dict):
                continue
            if not _instagram_webhook_messaging_needs_dm_worker(messaging):
                continue
            from core.tasks.instagram_dm import process_instagram_webhook_messaging_task

            process_instagram_webhook_messaging_task.delay(
                str(account.id),
                ig_account_id,
                dict(messaging),
            )
            logger.info(
                "instagram webhook enqueue account_id=%s keys=%s",
                account.id,
                list(messaging.keys()),
            )


def _record_dm_event(account: IntegrationAccount, messaging: dict[str, Any]) -> None:
    message = messaging.get("message") or {}
    mid = str(message.get("mid") or "")
    if message.get("is_edit"):
        ne = message.get("num_edit")
        external_id = f"{mid}:edit:{ne}"[:255] if mid else ""
    else:
        external_id = mid
    _ev, created = IntegrationEvent.objects.get_or_create(
        integration_account=account,
        event_type=INSTAGRAM_DM_MESSAGE.slug,
        external_event_id=external_id[:255],
        defaults={"payload": messaging},
    )
    logger.debug(
        "instagram integration_event account_id=%s created=%s",
        account.id,
        created,
    )


def process_webhook_request(request: HttpRequest) -> tuple[int, str]:
    """Entry point called from the router for POST webhook events."""
    raw_len = len(request.body or b"")

    if not verify_webhook_signature(request):
        logger.warning("instagram webhook POST unauthorized body_len=%s", raw_len)
        return 401, "unauthorized"

    try:
        body = request.body.decode("utf-8") if request.body else ""
        payload = json.loads(body) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning(
            "instagram webhook POST invalid_json body_len=%s err=%s", raw_len, exc
        )
        return 400, "invalid json"

    if not isinstance(payload, dict):
        logger.warning(
            "instagram webhook POST invalid_payload type=%s",
            type(payload).__name__,
        )
        return 400, "invalid payload"

    try:
        _handle_webhook_payload(payload)
    except Exception:
        logger.exception("instagram webhook POST dispatch failed")

    return 200, "ok"


def handle_webhook_verification(
    hub_mode: str, hub_verify_token: str, hub_challenge: str
) -> tuple[int, str]:
    """Respond to Meta's GET webhook verification handshake."""
    verify_token = str(getattr(settings, "INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "") or "")
    if hub_mode == "subscribe" and secrets.compare_digest(
        hub_verify_token, verify_token
    ):
        logger.info("instagram webhook verify ok")
        return 200, hub_challenge
    token_ok = bool(verify_token) and secrets.compare_digest(
        hub_verify_token, verify_token
    )
    logger.warning(
        "instagram webhook verify forbidden hub_mode=%r subscribe=%s token_ok=%s",
        hub_mode,
        hub_mode == "subscribe",
        token_ok,
    )
    return 403, "forbidden"


# ---------------------------------------------------------------------------
# Class API (tests / explicit DI); module functions remain the stable import surface.
# ---------------------------------------------------------------------------


class InstagramIntegrationService:
    """Instagram Business Login: OAuth state, token exchange, webhooks, Graph send."""

    store_oauth_state = staticmethod(store_oauth_state)
    consume_oauth_state = staticmethod(consume_oauth_state)
    build_instagram_oauth_url = staticmethod(build_instagram_oauth_url)
    instagram_exchange_code = staticmethod(instagram_exchange_code)
    instagram_get_long_lived_token = staticmethod(instagram_get_long_lived_token)
    instagram_get_user_info = staticmethod(instagram_get_user_info)
    instagram_send_message = staticmethod(instagram_send_message)
    instagram_create_image_media_container = staticmethod(
        instagram_create_image_media_container
    )
    instagram_publish_media_container = staticmethod(instagram_publish_media_container)
    instagram_publish_image_post = staticmethod(instagram_publish_image_post)
    instagram_enable_webhook_subscriptions = staticmethod(
        instagram_enable_webhook_subscriptions
    )
    instagram_disable_webhook_subscriptions = staticmethod(
        instagram_disable_webhook_subscriptions
    )
    get_access_token = staticmethod(get_access_token)
    get_ig_user_id = staticmethod(get_ig_user_id)
    connect_instagram_account = staticmethod(connect_instagram_account)
    disconnect_instagram_account = staticmethod(disconnect_instagram_account)
    verify_webhook_signature = staticmethod(verify_webhook_signature)
    process_instagram_webhook_messaging = staticmethod(
        process_instagram_webhook_messaging
    )
    process_webhook_request = staticmethod(process_webhook_request)
    handle_webhook_verification = staticmethod(handle_webhook_verification)


_instagram_integration_service: InstagramIntegrationService | None = None


def get_instagram_integration_service() -> InstagramIntegrationService:
    """Shared ``InstagramIntegrationService`` instance (methods are staticmethod-backed)."""
    global _instagram_integration_service
    if _instagram_integration_service is None:
        _instagram_integration_service = InstagramIntegrationService()
    return _instagram_integration_service
