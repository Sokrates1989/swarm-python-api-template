"""
Module: keycloak_profile_configuration.py

Description:
    Persists validated, operator-selected Keycloak realm/client identity into
    the ignored deployment environment and rebuilds the generated Swarm stack.
    The tracked Keycloak server remains the credential trust anchor.

Dependencies:
    - Python standard library.
    - Executable profile environment, model, and stack renderer modules.
    - Keycloak profile client identity model.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
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


@dataclass(frozen=True)
class KeycloakBootstrapValues:
    """Contain public values selected in the guided bootstrap dialogue.

    Attributes:
        server_url: Tracked Keycloak credential trust anchor.
        realm: Operator-selected realm name.
        realm_display_name: Operator-selected human-readable realm name.
        realm_settings: Operator-selected realm boolean settings.
        bootstrap_test_users_enabled: Whether profile test users should exist.
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
    bootstrap_test_users_enabled: bool
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
            bootstrap_test_users_enabled=(
                identity.bootstrap_test_users_enabled
            ),
            frontend_client_id=identity.frontend_client_id,
            backend_client_id=identity.backend_client_id,
            frontend_root_url=identity.frontend_root_url,
            api_root_url=identity.api_root_url,
            audience=identity.audience,
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
    for setting_name, environment_key in KEYCLOAK_REALM_SETTING_ENV_KEYS:
        updates[environment_key] = str(
            selected_settings[setting_name]
        ).lower()
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
