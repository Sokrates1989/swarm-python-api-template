"""
Module: keycloak_profile_configuration.py

Description:
    Persists validated, operator-selected Keycloak realm/client identity into
    the ignored deployment environment and rebuilds the generated Swarm stack.
    The tracked Keycloak server remains the credential trust anchor.

Dependencies:
    - Python standard library.
    - Executable profile environment, model, and stack renderer modules.
    - Keycloak profile client and application-access identity models.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse

from executable_profile import ExecutableProfile, load_executable_profile
from executable_profile_environment import write_deployment_env
from executable_profile_support import (
    KEYCLOAK_REALM_SETTING_ENV_KEYS,
    ExecutableProfileError,
)
from executable_stack_renderer import (
    compose_check,
    render_stack,
    write_stack,
)
from keycloak_profile_client import (
    KeycloakIdentity,
    KeycloakProfileError,
    load_keycloak_identity,
)
from keycloak_profile_application_access import (
    KeycloakBootstrapTestUser,
    KeycloakRealmRole,
)
from keycloak_profile_realm_configuration import (
    EMPTY_VALUE_SENTINEL,
    KeycloakEmailSenderSettings,
    KeycloakLocalizationSettings,
    KeycloakThemeSettings,
)


@dataclass(frozen=True)
class KeycloakBootstrapValues:
    """Contain public values selected in the guided bootstrap dialogue.

    Attributes:
        server_url: Tracked Keycloak credential trust anchor.
        realm: Operator-selected realm name.
        realm_display_name: Operator-selected human-readable realm name.
        realm_settings: Operator-selected realm boolean settings.
        theme_settings: Operator-selected realm themes.
        localization_settings: Operator-selected locale configuration.
        email_sender_settings: Operator-selected public SMTP sender settings.
        realm_roles: Application roles selected for this bootstrap run.
        bootstrap_test_users_enabled: Whether at least one temporary user is
            selected for this deployment.
        bootstrap_test_users: Individually configured profile and manual users
            without passwords.
        frontend_client_id: Operator-selected public PKCE client ID.
        backend_client_id: Operator-selected confidential service client ID.
        frontend_root_url: Operator-selected WebApp origin.
        api_root_url: Operator-selected backend root URL.
        audience: Operator-selected frontend token audience.
    """

    server_url: str
    realm: str
    realm_display_name: str
    realm_settings: tuple[tuple[str, bool], ...]
    theme_settings: KeycloakThemeSettings
    localization_settings: KeycloakLocalizationSettings
    email_sender_settings: KeycloakEmailSenderSettings
    realm_roles: tuple[KeycloakRealmRole, ...]
    bootstrap_test_users_enabled: bool
    bootstrap_test_users: tuple[KeycloakBootstrapTestUser, ...]
    frontend_client_id: str
    backend_client_id: str
    frontend_root_url: str
    api_root_url: str
    audience: str

    @classmethod
    def from_identity(
        cls,
        identity: KeycloakIdentity,
    ) -> "KeycloakBootstrapValues":
        """Create editable values from one active normalized identity.

        Args:
            identity: Current validated deployment identity.

        Returns:
            Public values suitable as prompt defaults.
        """

        return cls(
            server_url=identity.server_url,
            realm=identity.realm,
            realm_display_name=identity.realm_display_name,
            realm_settings=identity.realm_settings,
            theme_settings=identity.theme_settings,
            localization_settings=identity.localization_settings,
            email_sender_settings=identity.email_sender_settings,
            realm_roles=identity.realm_roles,
            bootstrap_test_users_enabled=(
                identity.bootstrap_test_users_enabled
            ),
            bootstrap_test_users=identity.bootstrap_test_users,
            frontend_client_id=identity.frontend_client_id,
            backend_client_id=identity.backend_client_id,
            frontend_root_url=identity.frontend_root_url,
            api_root_url=identity.api_root_url,
            audience=identity.audience,
        )

    def apply_access_selection(
        self,
        identity: KeycloakIdentity,
    ) -> KeycloakIdentity:
        """Apply the runtime-only role and user selection to an identity.

        Args:
            identity: Reloaded identity containing persisted public values.

        Returns:
            Identity used for planning and reconciliation in this process.

        Note:
            Passwords are not part of this object. Role/user choices remain
            runtime bootstrap intent; only the aggregate test-user lifecycle
            boolean is persisted for the next guided default.
        """

        return replace(
            identity,
            realm_roles=self.realm_roles,
            bootstrap_test_users_enabled=(
                self.bootstrap_test_users_enabled
            ),
            bootstrap_test_users=self.bootstrap_test_users,
        )


def _url_hostname(value: str, field: str) -> str:
    """Extract a hostname needed by the shared deployment environment.

    Args:
        value: Candidate public URL.
        field: Operator-facing field name for errors.

    Returns:
        Parsed hostname.

    Raises:
        ExecutableProfileError: If no hostname can be parsed. Full URL safety
            remains enforced by deployment validation.
    """

    hostname = urlparse(value).hostname
    if not hostname:
        raise ExecutableProfileError(f"{field} must contain a hostname.")
    return hostname


def _persistent_optional_value(value: str) -> str:
    """Encode an explicit empty public value without confusing it with fallback.

    Args:
        value: Operator-selected optional public text.

    Returns:
        Original text, or the documented empty sentinel for an empty value.
    """

    return value or EMPTY_VALUE_SENTINEL


def _updated_cors_origins(
    profile: ExecutableProfile,
    frontend_root_url: str,
) -> str:
    """Replace the prior active WebApp origin while retaining extra origins.

    Args:
        profile: Current validated deployment profile.
        frontend_root_url: Newly selected exact WebApp origin.

    Returns:
        Comma-separated, de-duplicated CORS origin list.
    """

    prior_root = profile.deployment["WEB_BASE_URL"].rstrip("/")
    current = (
        origin.strip()
        for origin in profile.deployment["CORS_ORIGINS"].split(",")
    )
    replaced = [
        frontend_root_url if origin == prior_root else origin
        for origin in current
        if origin
    ]
    if frontend_root_url not in replaced:
        replaced.append(frontend_root_url)
    return ",".join(dict.fromkeys(replaced))


def deployment_updates(
    profile: ExecutableProfile,
    values: KeycloakBootstrapValues,
) -> dict[str, str]:
    """Map selected Keycloak values to validated deployment fields.

    Args:
        profile: Current validated deployment profile.
        values: Public values selected by the operator.

    Returns:
        Root ``.env`` updates, including derived issuer, domains, and CORS.

    Raises:
        KeycloakProfileError: If the credential destination differs from the
            tracked site-profile trust anchor.
        ExecutableProfileError: If a selected root has no hostname.
    """

    current = load_keycloak_identity(profile)
    server_url = values.server_url.rstrip("/")
    if server_url != current.server_url:
        raise KeycloakProfileError(
            "Keycloak server URL is a fixed credential trust anchor; update "
            "the tracked site profile before authenticating to another server."
        )
    frontend_root = values.frontend_root_url.rstrip("/")
    api_root = values.api_root_url.rstrip("/")
    realm = values.realm.strip()
    updates = {
        "KEYCLOAK_ISSUER_URL": f"{server_url}/realms/{realm}",
        "KEYCLOAK_REALM": realm,
        "KEYCLOAK_REALM_DISPLAY_NAME": values.realm_display_name.strip(),
        "KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED": str(
            values.bootstrap_test_users_enabled
        ).lower(),
        "KEYCLOAK_AUDIENCE": values.audience.strip(),
        "KEYCLOAK_FRONTEND_CLIENT_ID": values.frontend_client_id.strip(),
        "KEYCLOAK_BACKEND_CLIENT_ID": values.backend_client_id.strip(),
        "WEB_BASE_URL": frontend_root,
        "WEB_DOMAIN": _url_hostname(frontend_root, "Frontend client root URL"),
        "CORS_ORIGINS": _updated_cors_origins(profile, frontend_root),
        "API_BASE_URL": api_root,
        "DOMAIN": _url_hostname(api_root, "Backend API client root URL"),
    }
    selected_settings = dict(values.realm_settings)
    if not values.email_sender_settings.enabled and (
        selected_settings["resetPasswordAllowed"]
        or selected_settings["verifyEmail"]
    ):
        raise KeycloakProfileError(
            "Password reset or verified-email enforcement requires a "
            "configured Keycloak realm email sender. Enable SMTP or disable "
            "both dependent realm settings."
        )
    for setting_name, environment_key in KEYCLOAK_REALM_SETTING_ENV_KEYS:
        updates[environment_key] = str(
            selected_settings[setting_name]
        ).lower()
    themes = values.theme_settings
    updates.update(
        {
            "KEYCLOAK_LOGIN_THEME": themes.login,
            "KEYCLOAK_ACCOUNT_THEME": themes.account,
            "KEYCLOAK_ADMIN_THEME": themes.admin,
            "KEYCLOAK_EMAIL_THEME": themes.email,
        }
    )
    localization = values.localization_settings
    updates.update(
        {
            "KEYCLOAK_INTERNATIONALIZATION_ENABLED": str(
                localization.enabled
            ).lower(),
            "KEYCLOAK_SUPPORTED_LOCALES": ",".join(
                localization.supported_locales
            ),
            "KEYCLOAK_DEFAULT_LOCALE": localization.default_locale,
        }
    )
    sender = values.email_sender_settings
    updates.update(
        {
            "KEYCLOAK_EMAIL_SENDER_ENABLED": str(sender.enabled).lower(),
            "KEYCLOAK_SMTP_FROM": sender.from_address,
            "KEYCLOAK_SMTP_FROM_DISPLAY_NAME": _persistent_optional_value(
                sender.from_display_name
            ),
            "KEYCLOAK_SMTP_REPLY_TO": _persistent_optional_value(
                sender.reply_to
            ),
            "KEYCLOAK_SMTP_REPLY_TO_DISPLAY_NAME": (
                _persistent_optional_value(sender.reply_to_display_name)
            ),
            "KEYCLOAK_SMTP_ENVELOPE_FROM": _persistent_optional_value(
                sender.envelope_from
            ),
            "KEYCLOAK_SMTP_HOST": sender.host,
            "KEYCLOAK_SMTP_PORT": str(sender.port),
            "KEYCLOAK_SMTP_STARTTLS": str(sender.start_tls).lower(),
            "KEYCLOAK_SMTP_SSL": str(sender.ssl).lower(),
            "KEYCLOAK_SMTP_AUTH": str(sender.authentication).lower(),
            "KEYCLOAK_SMTP_USERNAME": _persistent_optional_value(
                sender.username
            ),
        }
    )
    return updates


def _compose_check_content(root: Path, content: str) -> None:
    """Compose-validate generated stack content without replacing the stack.

    Args:
        root: Deployment checkout receiving the temporary file.
        content: Rendered Docker Compose/Swarm YAML.

    Returns:
        Nothing after Docker Compose accepts the temporary artifact.

    Raises:
        ExecutableProfileError: If Docker Compose rejects the artifact.
        OSError: If the temporary artifact cannot be managed.
    """

    descriptor, temporary_name = tempfile.mkstemp(
        dir=root,
        prefix=".keycloak-stack-check.",
        suffix=".yml",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as output:
            output.write(content)
        compose_check(temporary)
    finally:
        temporary.unlink(missing_ok=True)


def persist_keycloak_values(
    profile: ExecutableProfile,
    values: KeycloakBootstrapValues,
    *,
    check_compose: bool = True,
) -> tuple[ExecutableProfile, bool]:
    """Persist changed values and regenerate the active Swarm stack.

    Args:
        profile: Current validated deployment profile.
        values: Public values selected by the operator.
        check_compose: Run Docker Compose validation before replacing the stack.

    Returns:
        Reloaded profile and whether any deployment value changed.

    Raises:
        KeycloakProfileError: If the selected server differs from the tracked
            credential trust anchor.
        ExecutableProfileError: If validation, rendering, or Compose checking
            fails. The prior root environment is restored on such failures.
        OSError: If generated artifacts cannot be written or restored.
    """

    updates = deployment_updates(profile, values)
    changed = any(
        profile.deployment.get(key) != value
        for key, value in updates.items()
    )
    if not changed:
        return profile, False
    merged = {**profile.deployment, **updates}
    try:
        write_deployment_env(
            profile.root,
            profile.config_id,
            merged,
            force=True,
        )
        updated = load_executable_profile(profile.root)
        stack = render_stack(updated)
        if check_compose:
            _compose_check_content(profile.root, stack)
        write_stack(profile.root / "swarm-stack.yml", stack)
        return updated, True
    except BaseException:
        write_deployment_env(
            profile.root,
            profile.config_id,
            profile.deployment,
            force=True,
        )
        raise


__all__ = [
    "KeycloakBootstrapValues",
    "deployment_updates",
    "persist_keycloak_values",
]
