"""Table-driven definitions for Telegram and Instagram integration behavior."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Literal

from core.integrations.actionables import (
    Actionable,
    INSTAGRAM_MANAGE_COMMENTS,
    INSTAGRAM_MEDIA_INSIGHTS,
    INSTAGRAM_PUBLISH_EXTERNAL_RESOURCE,
    INSTAGRAM_REPLY_DM,
    INSTAGRAM_SEND_DIRECT_DM,
    TELEGRAM_REPLY_DM,
    TELEGRAM_SEND_DIRECT_DM,
)
from core.integrations.event_types import INSTAGRAM_DM_MESSAGE, TELEGRAM_PRIVATE_MESSAGE
from core.models import IntegrationAccount
from core.schemas.channel import InstagramDmChannel, TelegramPrivateChannel
from core.schemas.integration_account import SenderApprovalStatus
from core.schemas.send_target import SendTargetProvider


@dataclass(frozen=True)
class DmProviderConfig:
    integration_provider: IntegrationAccount.Provider
    inbound_event_slug: str
    reply_dm_actionable: Actionable
    direct_dm_actionable: Actionable
    send_target_provider: SendTargetProvider
    reply_sender_allowed: Callable[[str], bool]
    direct_sender_allowed: Callable[[str], bool]

    @property
    def reply_dm_slug(self) -> str:
        return self.reply_dm_actionable.slug

    @property
    def direct_dm_slug(self) -> str:
        return self.direct_dm_actionable.slug

    def build_integration_channel(
        self, integration_account_id: uuid.UUID, external_thread_id: str
    ) -> TelegramPrivateChannel | InstagramDmChannel:
        if self.integration_provider == IntegrationAccount.Provider.TELEGRAM:
            return TelegramPrivateChannel(
                type="telegram_private_chat",
                integration_account_id=integration_account_id,
                chat_id=external_thread_id,
            )
        return InstagramDmChannel(
            type="instagram_dm",
            integration_account_id=integration_account_id,
            recipient_igsid=external_thread_id,
        )


DM_PROVIDERS: Final[tuple[DmProviderConfig, ...]] = (
    DmProviderConfig(
        integration_provider=IntegrationAccount.Provider.TELEGRAM,
        inbound_event_slug=TELEGRAM_PRIVATE_MESSAGE.slug,
        reply_dm_actionable=TELEGRAM_REPLY_DM,
        direct_dm_actionable=TELEGRAM_SEND_DIRECT_DM,
        send_target_provider=SendTargetProvider.TELEGRAM,
        reply_sender_allowed=lambda s: s == SenderApprovalStatus.APPROVED,
        direct_sender_allowed=lambda s: s == SenderApprovalStatus.APPROVED,
    ),
    DmProviderConfig(
        integration_provider=IntegrationAccount.Provider.INSTAGRAM,
        inbound_event_slug=INSTAGRAM_DM_MESSAGE.slug,
        reply_dm_actionable=INSTAGRAM_REPLY_DM,
        direct_dm_actionable=INSTAGRAM_SEND_DIRECT_DM,
        send_target_provider=SendTargetProvider.INSTAGRAM,
        reply_sender_allowed=lambda s: s != SenderApprovalStatus.PENDING,
        direct_sender_allowed=lambda s: s != SenderApprovalStatus.PENDING,
    ),
)

_DM_BY_PROVIDER: Final[dict[IntegrationAccount.Provider, DmProviderConfig]] = {
    d.integration_provider: d for d in DM_PROVIDERS
}

ALL_REPLY_DM_SLUGS: Final[frozenset[str]] = frozenset(d.reply_dm_slug for d in DM_PROVIDERS)
ALL_DIRECT_DM_SLUGS: Final[frozenset[str]] = frozenset(d.direct_dm_slug for d in DM_PROVIDERS)


def dm_provider_config(
    provider: IntegrationAccount.Provider,
) -> DmProviderConfig | None:
    return _DM_BY_PROVIDER.get(provider)


def inbound_dm_definition(provider: IntegrationAccount.Provider) -> DmProviderConfig | None:
    return dm_provider_config(provider)


def exclusive_inbound_event_slugs() -> frozenset[str]:
    return frozenset(d.inbound_event_slug for d in DM_PROVIDERS)


WORKSPACE_CATALOG_ACTIONABLES: Final[
    Mapping[IntegrationAccount.Provider, tuple[Actionable, ...]]
] = {
    IntegrationAccount.Provider.TELEGRAM: (TELEGRAM_REPLY_DM, TELEGRAM_SEND_DIRECT_DM),
    IntegrationAccount.Provider.INSTAGRAM: (
        INSTAGRAM_REPLY_DM,
        INSTAGRAM_SEND_DIRECT_DM,
        INSTAGRAM_PUBLISH_EXTERNAL_RESOURCE,
        INSTAGRAM_MANAGE_COMMENTS,
        INSTAGRAM_MEDIA_INSIGHTS,
    ),
}


ACTIONABLE_CATALOG_PROVIDER_TO_INTEGRATION: Final[Mapping[str, IntegrationAccount.Provider]] = {
    "telegram": IntegrationAccount.Provider.TELEGRAM,
    "instagram": IntegrationAccount.Provider.INSTAGRAM,
}


def dm_integration_channel(
    account: IntegrationAccount, external_thread_id: str
) -> TelegramPrivateChannel | InstagramDmChannel | None:
    spec = dm_provider_config(account.provider)
    if spec is None:
        return None
    return spec.build_integration_channel(account.id, external_thread_id)


def is_reply_dm_slug(slug: str) -> bool:
    return slug in ALL_REPLY_DM_SLUGS


def is_direct_dm_slug(slug: str) -> bool:
    return slug in ALL_DIRECT_DM_SLUGS


DmSendKind = Literal["reply", "direct"]


def send_kind_for_action_slug(slug: str) -> DmSendKind | None:
    if slug in ALL_REPLY_DM_SLUGS:
        return "reply"
    if slug in ALL_DIRECT_DM_SLUGS:
        return "direct"
    return None
