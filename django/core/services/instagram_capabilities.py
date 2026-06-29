"""Map Instagram auth method + granted scopes to capability strings for gating."""

from __future__ import annotations

from core.schemas.integration_account import InstagramAuthMethod, InstagramCapability

INSTAGRAM_LOGIN_SCOPES = [
    "instagram_business_basic",
    "instagram_business_manage_messages",
    "instagram_business_content_publish",
]

FACEBOOK_LOGIN_SCOPES = [
    "instagram_basic",
    "pages_show_list",
    "pages_read_engagement",
    "instagram_content_publish",
    "instagram_manage_messages",
    "instagram_manage_comments",
    "instagram_manage_insights",
    "instagram_manage_contents",
]

_SCOPE_TO_CAPABILITY: dict[str, frozenset[InstagramCapability]] = {
    "instagram_business_basic": frozenset({InstagramCapability.BASIC}),
    "instagram_basic": frozenset({InstagramCapability.BASIC}),
    "instagram_business_content_publish": frozenset({InstagramCapability.PUBLISH}),
    "instagram_content_publish": frozenset({InstagramCapability.PUBLISH}),
    "instagram_business_manage_messages": frozenset({InstagramCapability.DM}),
    "instagram_manage_messages": frozenset({InstagramCapability.DM}),
    "instagram_business_manage_comments": frozenset({InstagramCapability.COMMENTS}),
    "instagram_manage_comments": frozenset({InstagramCapability.COMMENTS}),
    "instagram_business_manage_insights": frozenset({InstagramCapability.INSIGHTS}),
    "instagram_manage_insights": frozenset({InstagramCapability.INSIGHTS}),
    "instagram_business_manage_contents": frozenset({InstagramCapability.DELETE}),
    "instagram_manage_contents": frozenset({InstagramCapability.DELETE}),
}

_DEFAULT_INSTAGRAM_LOGIN_CAPABILITIES = frozenset(
    {
        InstagramCapability.BASIC,
        InstagramCapability.PUBLISH,
        InstagramCapability.DM,
    }
)


def resolve_auth_method(raw: str | None) -> InstagramAuthMethod:
    if raw == InstagramAuthMethod.FACEBOOK_LOGIN.value:
        return InstagramAuthMethod.FACEBOOK_LOGIN
    return InstagramAuthMethod.INSTAGRAM_LOGIN


def capabilities_from_scopes(
    *,
    auth_method: InstagramAuthMethod,
    granted_scopes: list[str] | None,
) -> list[str]:
    """Derive capability slugs from OAuth scopes; falls back to auth-method defaults."""
    caps: set[InstagramCapability] = set()
    for scope in granted_scopes or []:
        for cap in _SCOPE_TO_CAPABILITY.get(scope.strip(), frozenset()):
            caps.add(cap)
    if not caps and auth_method == InstagramAuthMethod.INSTAGRAM_LOGIN:
        caps = set(_DEFAULT_INSTAGRAM_LOGIN_CAPABILITIES)
    if not caps and auth_method == InstagramAuthMethod.FACEBOOK_LOGIN:
        caps = {InstagramCapability.BASIC}
    return sorted(c.value for c in caps)


def default_scopes_for_auth_method(auth_method: InstagramAuthMethod) -> list[str]:
    if auth_method == InstagramAuthMethod.FACEBOOK_LOGIN:
        return list(FACEBOOK_LOGIN_SCOPES)
    return list(INSTAGRAM_LOGIN_SCOPES)


def account_has_capability(capabilities: list[str] | None, required: str) -> bool:
    return required in (capabilities or [])
