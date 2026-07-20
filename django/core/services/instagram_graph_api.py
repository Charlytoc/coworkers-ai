"""Account-aware Instagram Graph API helpers for media, insights, and comments."""

from __future__ import annotations

from typing import Any

import requests

from core.models import IntegrationAccount
from core.schemas.integration_account import InstagramCapability
from core.services.instagram_capabilities import account_has_capability
from core.services.instagram_service import (
    INSTAGRAM_GRAPH_API_VERSION,
    _instagram_graph_error_message,
    get_access_token,
    get_ig_user_id,
    graph_base_for_account,
)

_MEDIA_FIELDS = "id,caption,media_type,timestamp,permalink,like_count,comments_count"
_COMMENT_FIELDS = "id,text,timestamp,username"


def _require_capability(account: IntegrationAccount, capability: str) -> None:
    caps = (account.config or {}).get("capabilities")
    if not account_has_capability(caps if isinstance(caps, list) else None, capability):
        raise ValueError(
            f"Instagram account lacks capability {capability!r}; reconnect with Facebook Login for full access."
        )


def _graph_get(account: IntegrationAccount, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    token = get_access_token(account)
    if not token:
        raise ValueError("Instagram token not configured")
    base = graph_base_for_account(account)
    query = dict(params or {})
    query["access_token"] = token
    resp = requests.get(f"{base}/{INSTAGRAM_GRAPH_API_VERSION}/{path}", params=query, timeout=30)
    try:
        data = resp.json()
    except ValueError as exc:
        raise ValueError("Instagram Graph returned invalid JSON") from exc
    if not isinstance(data, dict) or "error" in data:
        raise ValueError(_instagram_graph_error_message(data if isinstance(data, dict) else {}, "Graph GET failed"))
    return data


def _graph_post(
    account: IntegrationAccount, path: str, *, data: dict[str, Any] | None = None
) -> dict[str, Any]:
    token = get_access_token(account)
    if not token:
        raise ValueError("Instagram token not configured")
    base = graph_base_for_account(account)
    payload = dict(data or {})
    payload["access_token"] = token
    resp = requests.post(f"{base}/{INSTAGRAM_GRAPH_API_VERSION}/{path}", data=payload, timeout=30)
    try:
        body = resp.json()
    except ValueError as exc:
        raise ValueError("Instagram Graph returned invalid JSON") from exc
    if not isinstance(body, dict) or "error" in body:
        raise ValueError(_instagram_graph_error_message(body if isinstance(body, dict) else {}, "Graph POST failed"))
    return body


def _graph_delete(account: IntegrationAccount, path: str) -> dict[str, Any]:
    token = get_access_token(account)
    if not token:
        raise ValueError("Instagram token not configured")
    base = graph_base_for_account(account)
    resp = requests.delete(
        f"{base}/{INSTAGRAM_GRAPH_API_VERSION}/{path}",
        params={"access_token": token},
        timeout=30,
    )
    try:
        data = resp.json()
    except ValueError as exc:
        raise ValueError("Instagram Graph returned invalid JSON") from exc
    if not isinstance(data, dict) or "error" in data:
        raise ValueError(_instagram_graph_error_message(data if isinstance(data, dict) else {}, "Graph DELETE failed"))
    return data


def list_media(
    account: IntegrationAccount,
    *,
    limit: int = 25,
    after: str | None = None,
) -> dict[str, Any]:
    _require_capability(account, InstagramCapability.BASIC.value)
    ig_uid = get_ig_user_id(account)
    if not ig_uid:
        raise ValueError("ig_user_id not configured")
    params: dict[str, Any] = {"fields": _MEDIA_FIELDS, "limit": min(max(limit, 1), 50)}
    if after:
        params["after"] = after
    return _graph_get(account, f"{ig_uid}/media", params=params)


def get_media_insights(
    account: IntegrationAccount,
    media_id: str,
    *,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    _require_capability(account, InstagramCapability.INSIGHTS.value)
    mid = str(media_id or "").strip()
    if not mid:
        raise ValueError("media_id is required")
    metric_list = metrics or ["reach", "likes", "comments", "saved", "shares"]
    return _graph_get(account, f"{mid}/insights", params={"metric": ",".join(metric_list)})


def delete_media(account: IntegrationAccount, media_id: str) -> dict[str, Any]:
    _require_capability(account, InstagramCapability.DELETE.value)
    mid = str(media_id or "").strip()
    if not mid:
        raise ValueError("media_id is required")
    return _graph_delete(account, mid)


def list_comments(account: IntegrationAccount, media_id: str) -> dict[str, Any]:
    _require_capability(account, InstagramCapability.COMMENTS.value)
    mid = str(media_id or "").strip()
    if not mid:
        raise ValueError("media_id is required")
    return _graph_get(account, f"{mid}/comments", params={"fields": _COMMENT_FIELDS})


def reply_to_comment(account: IntegrationAccount, media_id: str, message: str) -> dict[str, Any]:
    _require_capability(account, InstagramCapability.COMMENTS.value)
    mid = str(media_id or "").strip()
    text = str(message or "").strip()
    if not mid:
        raise ValueError("media_id is required")
    if not text:
        raise ValueError("message is required")
    return _graph_post(account, f"{mid}/comments", data={"message": text})


def reply_to_comment_thread(account: IntegrationAccount, comment_id: str, message: str) -> dict[str, Any]:
    _require_capability(account, InstagramCapability.COMMENTS.value)
    cid = str(comment_id or "").strip()
    text = str(message or "").strip()
    if not cid:
        raise ValueError("comment_id is required")
    if not text:
        raise ValueError("message is required")
    return _graph_post(account, f"{cid}/replies", data={"message": text})


def delete_comment(account: IntegrationAccount, comment_id: str) -> dict[str, Any]:
    _require_capability(account, InstagramCapability.COMMENTS.value)
    cid = str(comment_id or "").strip()
    if not cid:
        raise ValueError("comment_id is required")
    return _graph_delete(account, cid)
