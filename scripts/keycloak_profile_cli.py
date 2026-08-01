"""
Module: keycloak_profile_cli.py

Description:
    Owns the interactive, secret-safe operator dialogue for generic Keycloak
    profile bootstrap. It guides the operator through public profile values,
    offers redacted request tracing, prints sanitized plans, reads the
    administrator password without echo, and delegates all mutation to the
    bootstrap coordinator.

Dependencies:
    - Python standard library.
    - Executable profile and Keycloak access-dialog, client, configuration,
      verification, and Docker-secret modules.
"""

from __future__ import annotations

import getpass
import json
from collections.abc import Mapping

from executable_profile import ExecutableProfile
from keycloak_profile_access_dialog import prompt_application_access
from keycloak_profile_application_access import required_test_user_passwords
from keycloak_profile_configuration import KeycloakBootstrapValues
from keycloak_profile_client import (
    KeycloakAdminClient,
    KeycloakIdentity,
    KeycloakProfileError,
)
from keycloak_profile_secret_bridge import docker_secret_exists
from keycloak_profile_verification import build_reconciliation_plan


def _print_application_access_target(identity: KeycloakIdentity) -> None:
    """Print declared application roles and temporary-user policy.

    Args:
        identity: Active normalized Keycloak identity.

    Returns:
        Nothing.
    """

    print("Forbidden default users:")
    usernames = identity.forbidden_default_usernames
    for username in usernames or ("none",):
        print(f"  - {username}")
    print("Application realm roles:")
    if identity.realm_roles:
        for role in identity.realm_roles:
            print(f"  - {role.name}: {role.description}")
    else:
        print("  - none")
    selected_count = sum(
        identity.bootstrap_test_users_enabled and user.selected_for_bootstrap
        for user in identity.bootstrap_test_users
    )
    print(f"Bootstrap users selected: {selected_count}")
    for user in identity.bootstrap_test_users:
        selected = (
            identity.bootstrap_test_users_enabled
            and user.selected_for_bootstrap
        )
        state = "create/update" if selected else "skip"
        print(
            f"  - [{state}] {user.username}: "
            f"{', '.join(user.realm_roles)}"
        )
    print("")
    if selected_count:
        print("[WARN] Temporary bootstrap test users are enabled.")
        print(
            "[WARN] Once you enter production mode, remember to delete "
            "those users."
        )
    else:
        print("No temporary bootstrap test users will be created.")


def print_target(
    profile: ExecutableProfile,
    identity: KeycloakIdentity,
) -> None:
    """Print the complete public desired state before authentication.

    Args:
        profile: Active executable profile.
        identity: Normalized Keycloak identity.

    Returns:
        Nothing.
    """

    print("Keycloak site-profile bootstrap")
    print("--------------------------------")
    print(f"  Profile:             {profile.config_id}")
    print(f"  Existing server:     {identity.server_url}")
    print(
        "  Admin console:       "
        f"{identity.server_url}/admin/master/console/#/{identity.realm}"
    )
    print(f"  Realm:               {identity.realm}")
    print(f"  Realm display name:  {identity.realm_display_name}")
    print(f"  Issuer:              {identity.issuer_url}")
    print(f"  Frontend client:     {identity.frontend_client_id}")
    print(f"  Backend client:      {identity.backend_client_id}")
    print(f"  Backend audience:    {identity.audience}")
    print(f"  Audience mapper:     {identity.audience_mapper_name}")
    print(f"  Docker secret name:  {identity.docker_secret}")
    print("")
    print("Realm settings:")
    for name, value in identity.realm_settings:
        print(f"  - {name}: {str(value).lower()}")
    print("Redirect URIs:")
    for value in identity.redirect_uris:
        print(f"  - {value}")
    print("Web origins:")
    for value in identity.web_origins:
        print(f"  - {value}")
    print("Backend service-account client roles:")
    for client_id, roles in identity.service_account_client_roles:
        print(f"  - {client_id}: {', '.join(roles)}")
    _print_application_access_target(identity)
    print("The role catalog is profile-owned; this run reconciles selections.")
    print("Social providers remain unchanged.")
    print("The confidential secret comes from Keycloak's real client response;")
    print("its value is never displayed or written to a file.")


def _prompt_value(label: str, default: str) -> str:
    """Return an entered public value or its active deployment default.

    Args:
        label: Operator-facing field label.
        default: Active profile/deployment-derived public value.

    Returns:
        Trimmed entered value, or ``default`` when Enter is pressed.
    """

    answer = input(f"{label} [{default}]: ").strip()
    return answer or default


def _prompt_boolean(label: str, default: bool) -> bool:
    """Return an explicit yes/no selection with an Enter default.

    Args:
        label: Operator-facing realm or test-user setting.
        default: Boolean selected when Enter is pressed.

    Returns:
        Operator-selected boolean.
    """

    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{label} [{hint}]: ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please enter y, n, or press Enter for the displayed default.")


def _prompt_realm_settings(
    identity: KeycloakIdentity,
) -> tuple[tuple[str, bool], ...]:
    """Collect every profile-owned realm boolean from the operator.

    Args:
        identity: Active identity providing deployment or profile defaults.

    Returns:
        Ordered realm-setting names and selected boolean values.
    """

    print("")
    print("Realm settings")
    print("--------------")
    configured = dict(identity.realm_settings)
    labels = (
        ("enabled", "Realm enabled"),
        ("registrationAllowed", "Allow user registration"),
        ("resetPasswordAllowed", "Allow password reset"),
        ("rememberMe", "Show Remember Me"),
        ("verifyEmail", "Require verified email"),
        ("loginWithEmailAllowed", "Allow login with email"),
    )
    return tuple(
        (name, _prompt_boolean(label, configured[name]))
        for name, label in labels
    )


def _prompt_public_identity_values(
    identity: KeycloakIdentity,
) -> dict[str, str]:
    """Collect realm, client, root-URL, and audience values.

    Args:
        identity: Active identity providing Enter-default values.

    Returns:
        Public selected values keyed for bootstrap-value construction.
    """

    realm = _prompt_value("Realm name", identity.realm)
    realm_display_name = _prompt_value(
        "Realm display name",
        identity.realm_display_name,
    )
    frontend_client_id = _prompt_value(
        "Frontend client ID",
        identity.frontend_client_id,
    )
    backend_client_id = _prompt_value(
        "Backend client ID",
        identity.backend_client_id,
    )
    frontend_root_url = _prompt_value(
        "Frontend client root URL",
        identity.frontend_root_url,
    )
    api_root_url = _prompt_value(
        "Backend API client root URL",
        identity.api_root_url,
    )
    audience_default = identity.audience
    if identity.audience == identity.backend_client_id:
        audience_default = backend_client_id
    return {
        "realm": realm,
        "realm_display_name": realm_display_name,
        "frontend_client_id": frontend_client_id,
        "backend_client_id": backend_client_id,
        "frontend_root_url": frontend_root_url,
        "api_root_url": api_root_url,
        "audience": _prompt_value("Backend audience", audience_default),
    }


def prompt_bootstrap_values(
    identity: KeycloakIdentity,
) -> KeycloakBootstrapValues:
    """Collect editable public bootstrap values with active defaults.

    Args:
        identity: Complete profile/deployment-derived Keycloak identity.

    Returns:
        Selected values ready for validation and deployment persistence.

    Note:
        The Keycloak server URL is printed as a fixed trust anchor because the
        administrator password must never be redirected by an interactive
        value entered immediately before authentication.
    """

    print("")
    print("Review Keycloak bootstrap values")
    print("--------------------------------")
    print("Press Enter to accept each active profile/deployment value.")
    print("Different values are validated, saved to .env, and used to rebuild")
    print("the stack before Keycloak authentication and reconciliation.")
    print("WebApp/mobile builds must use the same realm and client identity.")
    print("")
    print(f"Keycloak server URL (fixed trust anchor): {identity.server_url}")
    selected = _prompt_public_identity_values(identity)
    realm_settings = _prompt_realm_settings(identity)
    realm_roles, bootstrap_test_users = prompt_application_access(
        identity,
        _prompt_boolean,
    )
    bootstrap_test_users_enabled = any(
        user.selected_for_bootstrap for user in bootstrap_test_users
    )
    return KeycloakBootstrapValues(
        server_url=identity.server_url,
        realm=selected["realm"],
        realm_display_name=selected["realm_display_name"],
        realm_settings=realm_settings,
        realm_roles=realm_roles,
        bootstrap_test_users_enabled=bootstrap_test_users_enabled,
        bootstrap_test_users=bootstrap_test_users,
        frontend_client_id=selected["frontend_client_id"],
        backend_client_id=selected["backend_client_id"],
        frontend_root_url=selected["frontend_root_url"],
        api_root_url=selected["api_root_url"],
        audience=selected["audience"],
    )


def prompt_bootstrap_test_user_passwords(
    identity: KeycloakIdentity,
    plan: Mapping[str, object],
) -> dict[str, str]:
    """Read passwords needed for planned test-user creation or recovery.

    Args:
        identity: Active profile-derived Keycloak identity.
        plan: Sanitized live-state plan containing test-user actions.

    Returns:
        Runtime-only passwords keyed by username requiring a credential.

    Raises:
        KeycloakProfileError: If a password is empty or confirmation differs.
    """

    raw_actions = plan.get("bootstrapTestUserActions", {})
    actions = raw_actions if isinstance(raw_actions, Mapping) else {}
    required = set(required_test_user_passwords(actions))
    if not required:
        return {}
    print("")
    print("Temporary test-user credentials")
    print("--------------------------------")
    print("Passwords are read without echo and are sent only to Keycloak.")
    print("They are never written to the profile, .env, plan, or summary.")
    users = tuple(getattr(identity, "bootstrap_test_users", ()))
    by_name = {user.username: user for user in users}
    ordered = [user.username for user in users if user.username in required]
    ordered.extend(sorted(required - set(ordered)))
    passwords: dict[str, str] = {}
    for username in ordered:
        user = by_name.get(username)
        if user is not None:
            password_mode = (
                "temporary; change required at first login"
                if user.temporary_password
                else "regular; no forced first-login change"
            )
            print("")
            print(f"User: {username}")
            print(f"Roles: {', '.join(user.realm_roles)}")
            print(f"Password mode: {password_mode}")
        password = getpass.getpass(f"Initial password for {username}: ")
        confirmation = getpass.getpass(f"Confirm password for {username}: ")
        if not password:
            raise KeycloakProfileError(
                f"Password for test user {username!r} is required."
            )
        if password != confirmation:
            raise KeycloakProfileError(
                f"Password confirmation for test user {username!r} differs."
            )
        passwords[username] = password
    return passwords


def prompt_secret_safe_debug() -> bool:
    """Ask whether Admin API method/path/status tracing should be enabled.

    Returns:
        True only for an explicit ``y`` or ``yes`` answer. Request bodies,
        headers, query values, and credentials remain excluded from tracing.
    """

    answer = input(
        "Enable secret-safe Keycloak API request tracing? [y/N]: "
    ).strip()
    return answer.lower() in {"y", "yes"}


def prompt_admin_user(default: str = "admin") -> str:
    """Read the Keycloak administrator immediately before its password.

    Args:
        default: Username selected when the operator presses Enter.

    Returns:
        Explicit username, or ``default`` for an empty answer.
    """

    answer = input(f"Keycloak admin username [{default}]: ").strip()
    return answer or default


def print_plan(plan: dict[str, object]) -> None:
    """Print one sanitized live-state reconciliation plan.

    Args:
        plan: Plan returned by ``build_reconciliation_plan``.

    Returns:
        Nothing.
    """

    labels = (
        ("Realm", "realm"),
        ("Application roles", "realmRoles"),
        ("Frontend client", "frontendClient"),
        ("Backend client", "backendClient"),
        ("Audience mapper", "audienceMapper"),
        ("Frontend role scope", "frontendRealmRoleScope"),
        ("Service-account roles", "serviceAccountRoles"),
        ("Bootstrap test users", "bootstrapTestUsers"),
        ("Docker secret", "dockerSecret"),
    )
    print("")
    print("Authenticated live-state plan")
    print("-----------------------------")
    for label, key in labels:
        print(f"  {label:<23} {plan[key]}")
    blockers = plan["blockers"]
    if isinstance(blockers, list) and blockers:
        print("  Blockers:")
        for blocker in blockers:
            print(f"    - {blocker}")
    else:
        print("  Blockers:              none")
    if plan["dockerSecret"] == "keep-present-unverified":
        print("")
        print(
            "  Existing Docker secrets are opaque. This run can verify "
            "Keycloak state,"
        )
        print(
            "  but only explicit rotation can re-prove and replace that "
            "stored value."
        )


def confirm_apply(skip_confirmation: bool) -> bool:
    """Ask for Enter-default approval unless explicitly skipped.

    Args:
        skip_confirmation: Return immediately when ``--yes`` was supplied.

    Returns:
        Whether reconciliation should proceed.
    """

    if skip_confirmation:
        return True
    answer = input(
        "\nApply this sanitized plan and verify the result? [Y/n]: "
    ).strip()
    return answer.lower() not in {"n", "no"}


def authenticate_and_plan(
    identity: KeycloakIdentity,
    admin_user: str,
    *,
    replace_secret: bool,
    debug: bool = False,
) -> tuple[KeycloakAdminClient, bool, dict[str, object]]:
    """Authenticate once and inspect live state without mutation.

    Args:
        identity: Profile-derived Keycloak identity.
        admin_user: Existing Keycloak administrator username.
        replace_secret: Whether the requested plan includes rotation.
        debug: Emit secret-safe Admin API request traces when true.

    Returns:
        Authenticated client, Docker-secret presence, and sanitized plan.

    Raises:
        KeycloakProfileError: If password input, authentication, or inspection
            fails.
        KeycloakSecretBridgeError: If Docker secret state cannot be inspected.
    """

    password = getpass.getpass(
        f"Keycloak admin password for {admin_user}: "
    )
    if not password:
        raise KeycloakProfileError("Keycloak admin password is required.")
    print("\nAuthenticating and inspecting the existing Keycloak server...")
    client = KeycloakAdminClient(
        identity,
        admin_user,
        password,
        debug=debug,
    )
    password = ""
    docker_present = docker_secret_exists(identity.docker_secret)
    plan = build_reconciliation_plan(
        client,
        docker_secret_present=docker_present,
        replace_secret=replace_secret,
    )
    return client, docker_present, plan


def print_completion(
    identity: KeycloakIdentity,
    summary: dict[str, object],
) -> None:
    """Print verified bootstrap evidence and the admin-console link.

    Args:
        identity: Profile-derived Keycloak identity.
        summary: Secret-free reconciliation result.

    Returns:
        Nothing.
    """

    print("")
    print("Bootstrap completed and Keycloak state is verified:")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("")
    print(
        "Admin console: "
        f"{identity.server_url}/admin/master/console/#/{identity.realm}"
    )
    if any(
        identity.bootstrap_test_users_enabled and user.selected_for_bootstrap
        for user in identity.bootstrap_test_users
    ):
        print("")
        print("[WARN] Temporary bootstrap test users remain enabled.")
        print(
            "[WARN] Once you enter production mode, remember to delete "
            "those users."
        )
    if summary.get("dockerSecretBindingVerified") is False:
        print(
            "Docker secret binding: present but not readable by Swarm. Use "
            "the explicit"
        )
        print(
            "rotation menu while the app stack is stopped if you want a "
            "newly proven binding."
        )


__all__ = [
    "authenticate_and_plan",
    "confirm_apply",
    "print_completion",
    "print_plan",
    "print_target",
    "prompt_admin_user",
    "prompt_bootstrap_values",
    "prompt_bootstrap_test_user_passwords",
    "prompt_secret_safe_debug",
]
