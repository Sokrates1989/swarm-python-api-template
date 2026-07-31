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
    - Executable profile and Keycloak profile client, verification, and
      Docker-secret modules.
"""

from __future__ import annotations

import getpass
import json

from executable_profile import ExecutableProfile
from keycloak_profile_client import (
    KeycloakAdminClient,
    KeycloakIdentity,
    KeycloakProfileError,
)
from keycloak_profile_secret_bridge import docker_secret_exists
from keycloak_profile_verification import build_reconciliation_plan


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
    print(f"  Docker secret:       {identity.docker_secret}")
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
    print("Forbidden default users:")
    for username in identity.forbidden_default_usernames:
        print(f"  - {username}")
    print("")
    print("No users, passwords, example roles, or social providers are created.")
    print("The confidential secret comes from Keycloak's real client response;")
    print("its value is never displayed or written to a file.")


def _prompt_declared_value(label: str, expected: str) -> None:
    """Ask for one public value while preventing one-run identity drift.

    Args:
        label: Operator-facing field label.
        expected: Exact profile/deployment-derived public value.

    Returns:
        Nothing when Enter or the exact declared value is supplied.

    Raises:
        KeycloakProfileError: If the entered value differs from the selected
            site's cross-repository identity contract.
    """

    answer = input(f"{label} [{expected}]: ").strip()
    if answer and answer != expected:
        raise KeycloakProfileError(
            f"{label} is fixed by the selected site profile. Expected "
            f"{expected!r}; update the site config and matching application "
            "release profiles before bootstrapping a different identity."
        )


def prompt_bootstrap_values(identity: KeycloakIdentity) -> None:
    """Walk through the public bootstrap values with active defaults.

    Args:
        identity: Complete profile/deployment-derived Keycloak identity.

    Returns:
        Nothing after every declared value is explicitly accepted.

    Raises:
        KeycloakProfileError: If an answer attempts a one-run identity change.

    Note:
        Root URLs already reflect operator choices from the shared deployment
        setup. Realm and client IDs are cross-repository build contracts, so a
        bootstrap-only override would create an unusable deployment.
    """

    print("")
    print("Review Keycloak bootstrap values")
    print("--------------------------------")
    print("Press Enter to accept each active profile/deployment value.")
    print("Identity changes must be made through the shared site profile and")
    print("matching WebApp/backend release profiles, not only for this run.")
    print("")
    fields = (
        ("Keycloak server URL", identity.server_url),
        ("Realm name", identity.realm),
        ("Realm display name", identity.realm_display_name),
        ("Frontend client ID", identity.frontend_client_id),
        ("Backend client ID", identity.backend_client_id),
        ("Frontend client root URL", identity.frontend_root_url),
        ("Backend API client root URL", identity.api_root_url),
        ("Backend audience", identity.audience),
    )
    for label, expected in fields:
        _prompt_declared_value(label, expected)


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
        ("Frontend client", "frontendClient"),
        ("Backend client", "backendClient"),
        ("Audience mapper", "audienceMapper"),
        ("Service-account roles", "serviceAccountRoles"),
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
    "prompt_secret_safe_debug",
]
