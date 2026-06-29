"""Facebook Login for Business OAuth, page discovery, and pending page-picker state."""

from __future__ import annotations

import logging
import secrets
from typing import Any
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core.cache import cache

from core.schemas.integration_account import IntegrationAccountOnboarding
from core.services.instagram_capabilities import FACEBOOK_LOGIN_SCOPES

logger = logging.getLogger(__name__)

FACEBOOK_OAUTH_URL = "https://www.facebook.com/v25.0/dialog/oauth"
FACEBOOK_GRAPH_BASE = "https://graph.facebook.com"
FACEBOOK_GRAPH_API_VERSION = "v25.0"

_PAGES_PENDING_TTL = 600
_PAGES_PENDING_PREFIX = "ig_fb_pages_pending:"


def _app_id() -> str:
    return str(getattr(settings, "FACEBOOK_APP_ID", "") or "")


def _app_secret() -> str:
    return str(getattr(settings, "FACEBOOK_APP_SECRET", "") or "")


def _facebook_callback_url() -> str:
    base = str(getattr(settings, "SITE_URL", "http://127.0.0.1:8000")).rstrip("/")
    return f"{base}/api/integrations/instagram/facebook/callback/"


def _pages_pending_key(token: str) -> str:
    return f"{_PAGES_PENDING_PREFIX}{token}"


def build_facebook_oauth_url(state_token: str) -> str:
    params = {
        "client_id": _app_id(),
        "redirect_uri": _facebook_callback_url(),
        "scope": ",".join(FACEBOOK_LOGIN_SCOPES),
        "response_type": "code",
        "state": state_token,
    }
    return f"{FACEBOOK_OAUTH_URL}?{urlencode(params)}"


def facebook_exchange_code(code: str) -> dict[str, Any]:
    url = f"{FACEBOOK_GRAPH_BASE}/{FACEBOOK_GRAPH_API_VERSION}/oauth/access_token"
    resp = requests.get(
        url,
        params={
            "client_id": _app_id(),
            "client_secret": _app_secret(),
            "redirect_uri": _facebook_callback_url(),
            "code": code,
        },
        timeout=20,
    )
    data = resp.json()
    if "error" in data:
        msg = data["error"].get("message", "Facebook code exchange failed")
        logger.warning("facebook oauth exchange error=%s", data.get("error"))
        raise ValueError(msg)
    return data


def facebook_get_long_lived_token(short_token: str) -> dict[str, Any]:
    url = f"{FACEBOOK_GRAPH_BASE}/{FACEBOOK_GRAPH_API_VERSION}/oauth/access_token"
    resp = requests.get(
        url,
        params={
            "grant_type": "fb_exchange_token",
            "client_id": _app_id(),
            "client_secret": _app_secret(),
            "fb_exchange_token": short_token,
        },
        timeout=20,
    )
    data = resp.json()
    if "error" in data:
        logger.warning("facebook long_lived_token error=%s", data.get("error"))
        raise ValueError(data["error"].get("message", "Long-lived token exchange failed"))
    return data


def facebook_exchange_page_token_long_lived(page_token: str) -> dict[str, Any]:
    return facebook_get_long_lived_token(page_token)


def facebook_get_user_pages(user_token: str) -> list[dict[str, Any]]:
    url = f"{FACEBOOK_GRAPH_BASE}/{FACEBOOK_GRAPH_API_VERSION}/me/accounts"
    resp = requests.get(
        url,
        params={
            "fields": "id,name,access_token,instagram_business_account{id,username}",
            "access_token": user_token,
        },
        timeout=30,
    )
    data = resp.json()
    if "error" in data:
        logger.warning("facebook /me/accounts error=%s", data.get("error"))
        raise ValueError(data["error"].get("message", "Failed to list Facebook Pages"))
    rows = data.get("data")
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def pages_with_instagram(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in pages:
        ig = page.get("instagram_business_account")
        if isinstance(ig, dict) and ig.get("id"):
            out.append(page)
    return out


def page_option_from_row(page: dict[str, Any]) -> dict[str, str]:
    ig = page.get("instagram_business_account") or {}
    username = str(ig.get("username") or "").strip()
    return {
        "page_id": str(page.get("id") or ""),
        "page_name": str(page.get("name") or ""),
        "ig_user_id": str(ig.get("id") or ""),
        "ig_username": username,
        "display_label": (
            f"{page.get('name') or 'Page'} (@{username})" if username else str(page.get("name") or "Page")
        ),
    }


def store_pages_pending(
    *,
    workspace_id: int,
    user_id: int,
    onboarding: IntegrationAccountOnboarding,
    pages: list[dict[str, Any]],
    user_access_token: str,
) -> str:
    token = secrets.token_urlsafe(32)
    options = [page_option_from_row(p) for p in pages_with_instagram(pages)]
    page_tokens = {
        str(p.get("id") or ""): str(p.get("access_token") or "")
        for p in pages_with_instagram(pages)
        if p.get("id")
    }
    cache.set(
        _pages_pending_key(token),
        {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "onboarding": onboarding.model_dump(mode="json"),
            "pages": options,
            "page_tokens": page_tokens,
            "user_access_token": user_access_token,
        },
        _PAGES_PENDING_TTL,
    )
    return token


def consume_pages_pending(pending_token: str) -> dict[str, object] | None:
    key = _pages_pending_key(pending_token)
    payload = cache.get(key)
    if payload is None:
        return None
    cache.delete(key)
    return payload


def get_pages_pending(pending_token: str) -> dict[str, object] | None:
    return cache.get(_pages_pending_key(pending_token))


def resolve_page_from_pending(
    pending: dict[str, object], page_id: str
) -> tuple[dict[str, str], str] | None:
    pages = pending.get("pages")
    page_tokens = pending.get("page_tokens")
    if not isinstance(pages, list) or not isinstance(page_tokens, dict):
        return None
    pid = str(page_id or "").strip()
    for row in pages:
        if not isinstance(row, dict):
            continue
        if str(row.get("page_id") or "") == pid:
            token = str(page_tokens.get(pid) or "").strip()
            if not token:
                return None
            return row, token
    return None
