"""Telegram Bot API helpers, webhook handling, sender approval via cache, and ``IntegrationAccount.config`` conventions."""

from __future__ import annotations

import json
import secrets
import string
import uuid
from typing import Any

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import HttpRequest

from core.integrations.event_types import TELEGRAM_PRIVATE_MESSAGE
from core.models import IntegrationAccount, IntegrationEvent, Workspace
from core.schemas.integration_account import (
    INTEGRATION_ONBOARDING_CONFIG_KEY,
    IntegrationAccountOnboarding,
    SenderApprovalStatus,
)
from core.services.integration_senders import (
    get_sender,
    set_approval_status,
    upsert_sender,
)

TELEGRAM_API_BASE = "https://api.telegram.org"

CONFIG_WEBHOOK_PATH_TOKEN = "webhook_path_token"
CONFIG_SENDERS = "senders"

AUTH_BOT_TOKEN = "bot_token"
AUTH_WEBHOOK_SECRET = "webhook_secret_token"


def _approval_ttl() -> int:
    return int(getattr(settings, "TELEGRAM_APPROVAL_CACHE_TTL", 3600))


def cache_key_pending(integration_id: uuid.UUID, telegram_user_id: int) -> str:
    return f"tg_approval_pending:{integration_id}:{telegram_user_id}"


def cache_key_by_code(integration_id: uuid.UUID, code: str) -> str:
    return f"tg_approval_by_code:{integration_id}:{code}"


def telegram_get_me(bot_token: str) -> dict[str, Any]:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/getMe"
    response = requests.get(url, timeout=20)
    data = response.json()
    if not data.get("ok"):
        raise ValueError(data.get("description") or "Telegram getMe failed")
    return data["result"]


def telegram_set_webhook(bot_token: str, webhook_url: str, secret_token: str) -> None:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/setWebhook"
    payload = {
        "url": webhook_url,
        "secret_token": secret_token,
        "allowed_updates": ["message"],
    }
    response = requests.post(url, json=payload, timeout=20)
    data = response.json()
    if not data.get("ok"):
        raise ValueError(data.get("description") or "Telegram setWebhook failed")


def telegram_delete_webhook(bot_token: str) -> None:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/deleteWebhook"
    response = requests.post(url, json={"drop_pending_updates": False}, timeout=20)
    data = response.json()
    if not data.get("ok"):
        raise ValueError(data.get("description") or "Telegram deleteWebhook failed")


def telegram_send_message(bot_token: str, chat_id: int | str, text: str) -> dict[str, Any]:
    """Call Telegram ``sendMessage`` and return the API ``result`` message object."""
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": chat_id, "text": text},
        timeout=20,
    )
    data = response.json()
    if not data.get("ok"):
        raise ValueError(data.get("description") or "Telegram sendMessage failed")
    result = data.get("result")
    if not isinstance(result, dict):
        raise ValueError("Telegram sendMessage returned no message result")
    return result


def _telegram_send_media(
    *,
    bot_token: str,
    method: str,
    chat_id: int | str,
    file_url: str,
    file_field: str,
    caption: str | None,
    timeout: int,
) -> dict[str, Any]:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/{method}"
    payload: dict[str, Any] = {"chat_id": chat_id, file_field: file_url}
    if caption is not None and caption.strip():
        payload["caption"] = caption.strip()[:1024]
    response = requests.post(url, json=payload, timeout=timeout)
    data = response.json()
    if not data.get("ok"):
        raise ValueError(data.get("description") or f"Telegram {method} failed")
    result = data.get("result")
    if not isinstance(result, dict):
        raise ValueError(f"Telegram {method} returned no message result")
    return result


def telegram_send_photo(
    bot_token: str,
    chat_id: int | str,
    photo_url: str,
    *,
    caption: str | None = None,
) -> dict[str, Any]:
    """Send a photo by HTTPS URL (Telegram fetches the file)."""
    return _telegram_send_media(
        bot_token=bot_token,
        method="sendPhoto",
        chat_id=chat_id,
        file_url=photo_url,
        file_field="photo",
        caption=caption,
        timeout=120,
    )


def telegram_send_video(
    bot_token: str,
    chat_id: int | str,
    video_url: str,
    *,
    caption: str | None = None,
) -> dict[str, Any]:
    return _telegram_send_media(
        bot_token=bot_token,
        method="sendVideo",
        chat_id=chat_id,
        file_url=video_url,
        file_field="video",
        caption=caption,
        timeout=120,
    )


def telegram_send_audio(
    bot_token: str,
    chat_id: int | str,
    audio_url: str,
    *,
    caption: str | None = None,
) -> dict[str, Any]:
    return _telegram_send_media(
        bot_token=bot_token,
        method="sendAudio",
        chat_id=chat_id,
        file_url=audio_url,
        file_field="audio",
        caption=caption,
        timeout=120,
    )


def telegram_send_document(
    bot_token: str,
    chat_id: int | str,
    document_url: str,
    *,
    caption: str | None = None,
) -> dict[str, Any]:
    return _telegram_send_media(
        bot_token=bot_token,
        method="sendDocument",
        chat_id=chat_id,
        file_url=document_url,
        file_field="document",
        caption=caption,
        timeout=120,
    )


def find_integration_by_webhook_path_token(webhook_path_token: str) -> IntegrationAccount | None:
    token = (webhook_path_token or "").strip().rstrip("/")
    if not token:
        return None
    for row in IntegrationAccount.objects.filter(provider=IntegrationAccount.Provider.TELEGRAM).iterator():
        cfg = row.config or {}
        if cfg.get(CONFIG_WEBHOOK_PATH_TOKEN) == token:
            return row
    return None


def verify_webhook_secret_header(request: HttpRequest, account: IntegrationAccount) -> bool:
    expected = (account.auth or {}).get(AUTH_WEBHOOK_SECRET) or ""
    if not expected:
        return False
    got = request.headers.get("X-Telegram-Bot-Api-Secret-Token") or ""
    return secrets.compare_digest(str(expected), str(got))


def get_bot_token(account: IntegrationAccount) -> str:
    token = (account.auth or {}).get(AUTH_BOT_TOKEN) or ""
    return str(token).strip()


def is_telegram_user_approved(account: IntegrationAccount, telegram_user_id: int) -> bool:
    sender = get_sender(account, str(telegram_user_id))
    return bool(sender and sender.approval_status == SenderApprovalStatus.APPROVED)


def generate_approval_code(digits: int = 12) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(digits))


def store_pending_approval(account_id: uuid.UUID, telegram_user_id: int, code: str) -> None:
    ttl = _approval_ttl()
    cache.set(cache_key_by_code(account_id, code), str(telegram_user_id), ttl)
    cache.set(cache_key_pending(account_id, telegram_user_id), code, ttl)


def clear_pending_approval(account_id: uuid.UUID, telegram_user_id: int, code: str) -> None:
    cache.delete(cache_key_by_code(account_id, code))
    cache.delete(cache_key_pending(account_id, telegram_user_id))


def build_webhook_url(webhook_path_token: str) -> str:
    base = getattr(settings, "SITE_URL", "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/api/integrations/telegram/webhook/{webhook_path_token}/"


def telegram_sender_handle_from_message(message: dict[str, Any]) -> str | None:
    """Display handle for the human: ``@username`` when Telegram sends it, else numeric ``from.id``."""
    from_user = message.get("from") or {}
    chat = message.get("chat") or {}
    for bucket in (from_user, chat):
        if not isinstance(bucket, dict):
            continue
        raw = bucket.get("username")
        if isinstance(raw, str):
            u = raw.strip().lstrip("@")
            if u:
                return f"@{u}"
    uid = from_user.get("id")
    if uid is None:
        return None
    try:
        return str(int(uid))
    except (TypeError, ValueError):
        return str(uid).strip() or None


def ensure_telegram_config_defaults(config: dict[str, Any]) -> dict[str, Any]:
    out = dict(config) if config else {}
    if CONFIG_SENDERS not in out:
        out[CONFIG_SENDERS] = []
    return out


def handle_inbound_update(account: IntegrationAccount, update: dict[str, Any]) -> None:
    message = update.get("message")
    if not message or not isinstance(message, dict):
        return

    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        bot_token = get_bot_token(account)
        if bot_token and chat.get("id") is not None:
            telegram_send_message(
                bot_token,
                chat["id"],
                "This bot only accepts private messages for now.",
            )
        return

    from_user = message.get("from") or {}
    uid = from_user.get("id")
    if uid is None:
        return
    telegram_user_id = int(uid)
    chat_id = chat.get("id")
    if chat_id is None:
        return

    bot_token = get_bot_token(account)
    if not bot_token:
        return

    if is_telegram_user_approved(account, telegram_user_id):
        _record_private_message_event(account, message, update)
        from core.services.telegram_events_processor import process_approved_message

        process_approved_message(account, message)
        return

    upsert_sender(
        account,
        str(telegram_user_id),
        default_status=SenderApprovalStatus.PENDING,
        handle=telegram_sender_handle_from_message(message),
    )

    pending_key = cache_key_pending(account.id, telegram_user_id)
    existing_code = cache.get(pending_key)
    if existing_code and isinstance(existing_code, str):
        telegram_send_message(
            bot_token,
            chat_id,
            f"Your approval code is still: {existing_code}. Enter it in the workspace to approve this sender.",
        )
        return

    code = generate_approval_code()
    store_pending_approval(account.id, telegram_user_id, code)
    telegram_send_message(
        bot_token,
        chat_id,
        (
            f"Your approval code is: {code}\n"
            "Someone with access to the workspace must enter this code in the app to approve you."
        ),
    )


def _record_private_message_event(
    account: IntegrationAccount,
    message: dict[str, Any],
    update: dict[str, Any],
) -> None:
    raw_uid = update.get("update_id")
    external_id = str(raw_uid) if raw_uid is not None else ""

    IntegrationEvent.objects.get_or_create(
        integration_account=account,
        event_type=TELEGRAM_PRIVATE_MESSAGE.slug,
        external_event_id=external_id[:255],
        defaults={"payload": {"update": update, "message": message}},
    )


def process_webhook_request(request: HttpRequest, webhook_path_token: str) -> tuple[int, str]:
    account = find_integration_by_webhook_path_token(webhook_path_token)
    if account is None or account.provider != IntegrationAccount.Provider.TELEGRAM:
        return 404, "not found"

    if not verify_webhook_secret_header(request, account):
        return 401, "unauthorized"

    if account.status not in (
        IntegrationAccount.Status.ACTIVE,
        IntegrationAccount.Status.PENDING,
    ):
        return 403, "integration inactive"

    try:
        body = request.body.decode("utf-8") if request.body else ""
        update = json.loads(body) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 400, "invalid json"

    if not isinstance(update, dict):
        return 400, "invalid payload"

    try:
        handle_inbound_update(account, update)
    except ValueError as exc:
        return 502, str(exc)
    return 200, "ok"


def connect_telegram_bot(
    *,
    workspace: Workspace,
    user,
    bot_token: str,
    display_name: str | None,
    onboarding: IntegrationAccountOnboarding,
) -> IntegrationAccount:
    bot_token = (bot_token or "").strip()
    if not bot_token:
        raise ValueError("bot_token is required")

    me = telegram_get_me(bot_token)
    bot_id = me.get("id")
    if bot_id is None:
        raise ValueError("invalid getMe response")

    external_id = str(bot_id)
    username = (me.get("username") or "") or ""
    default_label = f"@{username}" if username else external_id
    label = (display_name or "").strip() or default_label

    webhook_path_token = secrets.token_urlsafe(32)
    webhook_secret = secrets.token_urlsafe(32)
    webhook_url = build_webhook_url(webhook_path_token)

    with transaction.atomic():
        account, _created = IntegrationAccount.objects.get_or_create(
            workspace=workspace,
            provider=IntegrationAccount.Provider.TELEGRAM,
            external_account_id=external_id,
            defaults={
                "created_by": user if getattr(user, "pk", None) else None,
                "display_name": label[:200],
                "status": IntegrationAccount.Status.ACTIVE,
                "config": {
                    **ensure_telegram_config_defaults(
                        {CONFIG_WEBHOOK_PATH_TOKEN: webhook_path_token}
                    ),
                    INTEGRATION_ONBOARDING_CONFIG_KEY: onboarding.model_dump(mode="json"),
                },
            },
        )
        if not _created:
            cfg = ensure_telegram_config_defaults(dict(account.config or {}))
            cfg[CONFIG_WEBHOOK_PATH_TOKEN] = webhook_path_token
            cfg[INTEGRATION_ONBOARDING_CONFIG_KEY] = onboarding.model_dump(mode="json")
            account.config = cfg
            account.display_name = label[:200] or account.display_name
            account.status = IntegrationAccount.Status.ACTIVE

        account.auth = {
            AUTH_BOT_TOKEN: bot_token,
            AUTH_WEBHOOK_SECRET: webhook_secret,
        }
        account.save()

    from core.tasks.integration_onboarding import provision_integration_default_job

    provision_integration_default_job.delay(str(account.id))

    telegram_set_webhook(bot_token, webhook_url, webhook_secret)

    return account


def disconnect_telegram_bot(account: IntegrationAccount) -> None:
    """Remove the Telegram integration row after dropping the webhook (hard delete)."""
    if account.provider != IntegrationAccount.Provider.TELEGRAM:
        raise ValueError("not a telegram integration")
    bot_token = get_bot_token(account)
    if bot_token:
        try:
            telegram_delete_webhook(bot_token)
        except ValueError:
            pass
    account.delete()


def approve_sender_code(*, account: IntegrationAccount, code: str) -> str:
    code = "".join(c for c in (code or "") if c.isdigit())
    if len(code) != 12:
        raise ValueError("code must be 12 digits")

    uid_raw = cache.get(cache_key_by_code(account.id, code))
    if not uid_raw:
        raise ValueError("invalid or expired code")

    telegram_user_id = str(uid_raw).strip()
    if not telegram_user_id:
        raise ValueError("invalid or expired code")

    telegram_user_int = int(telegram_user_id)

    set_approval_status(
        account,
        telegram_user_id,
        SenderApprovalStatus.APPROVED,
    )

    clear_pending_approval(account.id, telegram_user_int, code)

    return telegram_user_id
