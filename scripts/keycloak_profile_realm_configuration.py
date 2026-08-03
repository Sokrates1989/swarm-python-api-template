"""
Module: keycloak_profile_realm_configuration.py

Description:
    Models and normalizes the generic realm presentation, localization, and
    SMTP sender settings owned by executable Keycloak site profiles. Public
    values may be overridden by the generated deployment environment; SMTP
    credentials deliberately never enter this module or persistent config.

Dependencies:
    - Python standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, cast


DEFAULT_THEME = "default"
EMPTY_VALUE_SENTINEL = "<empty>"


@dataclass(frozen=True)
class KeycloakThemeSettings:
    """Describe realm-owned Keycloak theme selections.

    Attributes:
        login: Login theme name, or ``default`` for the server default.
        account: Account-console theme name, or ``default``.
        admin: Admin-console theme name, or ``default``.
        email: Email-rendering theme name, or ``default``.
    """

    login: str
    account: str
    admin: str
    email: str


@dataclass(frozen=True)
class KeycloakLocalizationSettings:
    """Describe realm internationalization and locale defaults.

    Attributes:
        enabled: Whether users may select supported realm locales.
        supported_locales: Ordered locale identifiers offered by the realm.
        default_locale: Realm locale used when no user preference exists.
    """

    enabled: bool
    supported_locales: tuple[str, ...]
    default_locale: str


@dataclass(frozen=True)
class KeycloakEmailSenderSettings:
    """Describe public realm SMTP and sender configuration.

    Attributes:
        enabled: Whether this profile owns a configured SMTP sender.
        from_address: Sender mailbox used for realm email.
        from_display_name: Optional human-readable sender name.
        reply_to: Optional reply-to mailbox.
        reply_to_display_name: Optional reply-to display name.
        envelope_from: Optional SMTP envelope sender mailbox.
        host: SMTP server hostname.
        port: SMTP server TCP port.
        start_tls: Whether STARTTLS is required.
        ssl: Whether implicit TLS is required.
        authentication: Whether SMTP authentication is required.
        username: Public SMTP login name; its password is runtime-only.
    """

    enabled: bool
    from_address: str
    from_display_name: str
    reply_to: str
    reply_to_display_name: str
    envelope_from: str
    host: str
    port: int
    start_tls: bool
    ssl: bool
    authentication: bool
    username: str


def _active_text(
    deployment: Mapping[str, str],
    key: str,
    default: object,
) -> str:
    """Resolve one public text override with a profile fallback.

    Args:
        deployment: Validated generated deployment environment.
        key: Environment field holding an optional override.
        default: Profile-declared fallback value.

    Returns:
        Deployment value when populated, otherwise the profile value.
    """

    value = deployment.get(key, "")
    return value if value != "" else str(default)


def _active_boolean(
    deployment: Mapping[str, str],
    key: str,
    default: bool,
) -> bool:
    """Resolve one validated boolean override with a profile fallback.

    Args:
        deployment: Validated generated deployment environment.
        key: Environment field containing ``true``, ``false``, or empty.
        default: Profile-declared fallback used for an empty value.

    Returns:
        Active boolean selection.
    """

    value = deployment.get(key, "")
    return default if value == "" else value == "true"


def _active_optional_text(
    deployment: Mapping[str, str],
    key: str,
    default: object,
) -> str:
    """Resolve optional text while honoring an explicit empty sentinel.

    Args:
        deployment: Validated generated deployment environment.
        key: Environment field holding an optional override.
        default: Profile-declared fallback value.

    Returns:
        Empty text for ``<empty>``, otherwise the active override or fallback.
    """

    value = deployment.get(key, "")
    if value == EMPTY_VALUE_SENTINEL:
        return ""
    return value if value != "" else str(default)


def load_theme_settings(
    auth: Mapping[str, object],
    deployment: Mapping[str, str],
) -> KeycloakThemeSettings:
    """Load active theme choices from profile defaults and deployment state.

    Args:
        auth: Validated Keycloak authentication profile mapping.
        deployment: Validated generated deployment environment.

    Returns:
        Active immutable theme settings.
    """

    configured = cast(Mapping[str, object], auth["themes"])
    return KeycloakThemeSettings(
        login=_active_text(
            deployment, "KEYCLOAK_LOGIN_THEME", configured["login"]
        ),
        account=_active_text(
            deployment, "KEYCLOAK_ACCOUNT_THEME", configured["account"]
        ),
        admin=_active_text(
            deployment, "KEYCLOAK_ADMIN_THEME", configured["admin"]
        ),
        email=_active_text(
            deployment, "KEYCLOAK_EMAIL_THEME", configured["email"]
        ),
    )


def load_localization_settings(
    auth: Mapping[str, object],
    deployment: Mapping[str, str],
) -> KeycloakLocalizationSettings:
    """Load active internationalization settings.

    Args:
        auth: Validated Keycloak authentication profile mapping.
        deployment: Validated generated deployment environment.

    Returns:
        Active immutable localization settings.
    """

    configured = cast(Mapping[str, object], auth["localization"])
    raw_locales = _active_text(
        deployment,
        "KEYCLOAK_SUPPORTED_LOCALES",
        ",".join(str(item) for item in configured["supportedLocales"]),
    )
    return KeycloakLocalizationSettings(
        enabled=_active_boolean(
            deployment,
            "KEYCLOAK_INTERNATIONALIZATION_ENABLED",
            bool(configured["enabled"]),
        ),
        supported_locales=tuple(
            item.strip() for item in raw_locales.split(",") if item.strip()
        ),
        default_locale=_active_text(
            deployment,
            "KEYCLOAK_DEFAULT_LOCALE",
            configured["defaultLocale"],
        ),
    )


def load_email_sender_settings(
    auth: Mapping[str, object],
    deployment: Mapping[str, str],
) -> KeycloakEmailSenderSettings:
    """Load active public SMTP sender settings without a password.

    Args:
        auth: Validated Keycloak authentication profile mapping.
        deployment: Validated generated deployment environment.

    Returns:
        Active immutable email-sender settings.
    """

    configured = cast(Mapping[str, object], auth["emailSender"])
    return KeycloakEmailSenderSettings(
        enabled=_active_boolean(
            deployment,
            "KEYCLOAK_EMAIL_SENDER_ENABLED",
            bool(configured["enabled"]),
        ),
        from_address=_active_text(
            deployment, "KEYCLOAK_SMTP_FROM", configured["from"]
        ),
        from_display_name=_active_optional_text(
            deployment,
            "KEYCLOAK_SMTP_FROM_DISPLAY_NAME",
            configured["fromDisplayName"],
        ),
        reply_to=_active_optional_text(
            deployment, "KEYCLOAK_SMTP_REPLY_TO", configured["replyTo"]
        ),
        reply_to_display_name=_active_optional_text(
            deployment,
            "KEYCLOAK_SMTP_REPLY_TO_DISPLAY_NAME",
            configured["replyToDisplayName"],
        ),
        envelope_from=_active_optional_text(
            deployment,
            "KEYCLOAK_SMTP_ENVELOPE_FROM",
            configured["envelopeFrom"],
        ),
        host=_active_text(
            deployment, "KEYCLOAK_SMTP_HOST", configured["host"]
        ),
        port=int(
            _active_text(
                deployment, "KEYCLOAK_SMTP_PORT", configured["port"]
            )
        ),
        start_tls=_active_boolean(
            deployment,
            "KEYCLOAK_SMTP_STARTTLS",
            bool(configured["startTls"]),
        ),
        ssl=_active_boolean(
            deployment,
            "KEYCLOAK_SMTP_SSL",
            bool(configured["ssl"]),
        ),
        authentication=_active_boolean(
            deployment,
            "KEYCLOAK_SMTP_AUTH",
            bool(configured["authentication"]),
        ),
        username=_active_optional_text(
            deployment, "KEYCLOAK_SMTP_USERNAME", configured["username"]
        ),
    )


def theme_realm_payload(settings: KeycloakThemeSettings) -> dict[str, Any]:
    """Convert theme selections to Keycloak realm representation fields.

    Args:
        settings: Active realm theme selections.

    Returns:
        Realm fields with ``None`` used to restore server defaults.
    """

    def selected(value: str) -> str | None:
        """Map the public default sentinel to Keycloak's null selection.

        Args:
            value: Public installed-theme name or ``default`` sentinel.

        Returns:
            Installed theme name, or ``None`` to inherit the server default.
        """

        return None if value == DEFAULT_THEME else value

    return {
        "loginTheme": selected(settings.login),
        "accountTheme": selected(settings.account),
        "adminTheme": selected(settings.admin),
        "emailTheme": selected(settings.email),
    }


def localization_realm_payload(
    settings: KeycloakLocalizationSettings,
) -> dict[str, Any]:
    """Convert localization choices to Keycloak realm fields.

    Args:
        settings: Active localization settings.

    Returns:
        Internationalization fields owned by the profile.
    """

    return {
        "internationalizationEnabled": settings.enabled,
        "supportedLocales": list(settings.supported_locales),
        "defaultLocale": settings.default_locale,
    }


def smtp_public_payload(
    settings: KeycloakEmailSenderSettings,
) -> dict[str, str]:
    """Build Keycloak's public SMTP map without credential material.

    Args:
        settings: Active public email-sender settings.

    Returns:
        Empty mapping when disabled, otherwise all profile-owned public SMTP
        fields. No password field can be produced by this function.
    """

    if not settings.enabled:
        return {}
    return {
        "from": settings.from_address,
        "fromDisplayName": settings.from_display_name,
        "replyTo": settings.reply_to,
        "replyToDisplayName": settings.reply_to_display_name,
        "envelopeFrom": settings.envelope_from,
        "host": settings.host,
        "port": str(settings.port),
        "starttls": str(settings.start_tls).lower(),
        "ssl": str(settings.ssl).lower(),
        "auth": str(settings.authentication).lower(),
        "user": settings.username,
    }


__all__ = [
    "DEFAULT_THEME",
    "EMPTY_VALUE_SENTINEL",
    "KeycloakEmailSenderSettings",
    "KeycloakLocalizationSettings",
    "KeycloakThemeSettings",
    "load_email_sender_settings",
    "load_localization_settings",
    "load_theme_settings",
    "localization_realm_payload",
    "smtp_public_payload",
    "theme_realm_payload",
]
