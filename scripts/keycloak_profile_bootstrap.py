"""
Module: keycloak_profile_bootstrap.py

Description:
    Coordinates generic, site-profile-driven Keycloak reconciliation against
    an existing server and bridges the confidential backend credential to its
    declared Docker secret. No application identity or Keycloak deployment
    path is embedded here.

Dependencies:
    - Python standard library.
    - Executable profile, Keycloak client/reconciliation/role, and Docker
      secret bridge modules.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from executable_profile import (
    ExecutableProfile,
    ExecutableProfileError,
    load_executable_profile,
)
from keycloak_profile_client import (
    KeycloakAdminClient,
    KeycloakIdentity,
    KeycloakProfileError,
    load_keycloak_identity,
    resolve_client_uuid as _resolve_client_uuid,
)
from keycloak_profile_reconciliation import (
    backend_payload as _backend_payload,
    ensure_audience_mapper,
    ensure_client,
    ensure_realm,
    frontend_payload as _frontend_payload,
    get_client_secret,
    regenerate_client_secret,
)
from keycloak_profile_roles import (
    KeycloakRoleError,
    ensure_service_account_roles,
)
from keycloak_profile_secret_bridge import (
    KeycloakSecretBridgeError,
    docker_secret_exists,
    stack_is_running,
    write_docker_secret,
)


def _preflight_secret_state(
    profile: ExecutableProfile,
    identity: KeycloakIdentity,
    client: KeycloakAdminClient,
    *,
    replace_secret: bool,
) -> tuple[bool, bool]:
    """Check stack, backend-client, and Docker-secret state before client writes.

    Args:
        profile: Active executable site profile.
        identity: Profile-derived Keycloak identity.
        client: Authenticated Keycloak Admin client.
        replace_secret: Whether explicit rotation was requested.

    Returns:
        Whether the backend client is missing and whether its Docker secret
        already exists.

    Raises:
        KeycloakProfileError: If stale secret state requires explicit rotation.
        KeycloakSecretBridgeError: If Docker state cannot be inspected.
    """

    if replace_secret and stack_is_running(profile.stack_name):
        raise KeycloakProfileError(
            "Stop the selected stack before rotating its Keycloak client secret."
        )
    backend_missing = (
        _resolve_client_uuid(client, identity.backend_client_id) is None
    )
    docker_present = docker_secret_exists(identity.docker_secret)
    if backend_missing and docker_present and not replace_secret:
        raise KeycloakProfileError(
            "The backend Keycloak client is missing while its Docker secret "
            "already exists. Use explicit secret rotation after confirming "
            "the selected stack is stopped."
        )
    return backend_missing, docker_present


def _reconcile_clients(
    client: KeycloakAdminClient,
    identity: KeycloakIdentity,
) -> tuple[str, str, str, str, str, str]:
    """Reconcile both clients, audience mapper, and exact service-account roles.

    Args:
        client: Authenticated Keycloak Admin client.
        identity: Profile-derived Keycloak identity.

    Returns:
        Frontend UUID, frontend action, backend UUID, backend action, mapper
        action, and role action encoded as a six-item tuple.

    Raises:
        KeycloakProfileError: If client or mapper reconciliation fails.
        KeycloakRoleError: If service-account role state is unsafe.
    """

    frontend_uuid, frontend_action = ensure_client(
        client,
        _frontend_payload(identity),
    )
    backend_uuid, backend_action = ensure_client(
        client,
        _backend_payload(identity),
    )
    mapper_action = ensure_audience_mapper(client, frontend_uuid)
    roles_action = ensure_service_account_roles(client, backend_uuid)
    return (
        frontend_uuid,
        frontend_action,
        backend_uuid,
        backend_action,
        mapper_action,
        roles_action,
    )


def _bridge_client_secret(
    profile: ExecutableProfile,
    identity: KeycloakIdentity,
    client: KeycloakAdminClient,
    backend_uuid: str,
    backend_action: str,
    *,
    docker_secret_present: bool,
    replace_secret: bool,
) -> str:
    """Keep, create, or rotate the profile-declared Docker client secret.

    Args:
        profile: Active executable site profile.
        identity: Profile-derived Keycloak identity.
        client: Authenticated Keycloak Admin client.
        backend_uuid: Confidential backend client UUID.
        backend_action: Result of backend client reconciliation.
        docker_secret_present: Whether Docker already has the target secret.
        replace_secret: Whether explicit rotation was requested.

    Returns:
        Docker secret action.

    Raises:
        KeycloakProfileError: If Keycloak omits the credential.
        KeycloakSecretBridgeError: If Docker cannot create or replace it.
    """

    if docker_secret_present and not replace_secret:
        return "kept"
    if replace_secret and backend_action != "created":
        secret = regenerate_client_secret(client, backend_uuid)
    else:
        secret = get_client_secret(client, backend_uuid)
    try:
        return write_docker_secret(
            profile,
            identity,
            secret,
            replace=replace_secret,
        )
    finally:
        secret = ""


def reconcile(
    profile: ExecutableProfile,
    admin_user: str,
    admin_password: str,
    *,
    replace_secret: bool,
) -> dict[str, str]:
    """Reconcile realm, clients, roles, audience, and Docker secret.

    Args:
        profile: Active executable profile.
        admin_user: Existing Keycloak administrator username.
        admin_password: Administrator password retained only in memory.
        replace_secret: Rotate and replace the client secret when true.

    Returns:
        Secret-free action summary.

    Raises:
        KeycloakProfileError: If Keycloak state is unsafe or unavailable.
        KeycloakRoleError: If service-account roles exceed the declaration.
        KeycloakSecretBridgeError: If Docker state is unsafe or unavailable.
    """

    identity = load_keycloak_identity(profile)
    client = KeycloakAdminClient(identity, admin_user, admin_password)
    realm_action = ensure_realm(client)
    _, docker_present = _preflight_secret_state(
        profile,
        identity,
        client,
        replace_secret=replace_secret,
    )
    (
        _,
        frontend_action,
        backend_uuid,
        backend_action,
        mapper_action,
        roles_action,
    ) = _reconcile_clients(client, identity)
    docker_action = _bridge_client_secret(
        profile,
        identity,
        client,
        backend_uuid,
        backend_action,
        docker_secret_present=docker_present,
        replace_secret=replace_secret,
    )
    return {
        "profile": profile.config_id,
        "realm": identity.realm,
        "realmAction": realm_action,
        "frontendClient": identity.frontend_client_id,
        "frontendAction": frontend_action,
        "backendClient": identity.backend_client_id,
        "backendAction": backend_action,
        "audience": identity.audience,
        "audienceMapperAction": mapper_action,
        "serviceAccountRolesAction": roles_action,
        "dockerSecret": identity.docker_secret,
        "dockerSecretAction": docker_action,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the profile-driven Keycloak bootstrap CLI parser.

    Returns:
        Configured argument parser.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Reconcile the active site profile's Keycloak realm and clients."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Deployment repository root containing .env.",
    )
    parser.add_argument(
        "--admin-user",
        default="admin",
        help="Existing Keycloak administrator username.",
    )
    parser.add_argument(
        "--replace-secret",
        action="store_true",
        help=(
            "Rotate the Keycloak client secret and replace its Docker secret. "
            "The selected stack must be stopped."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run profile-driven Keycloak reconciliation.

    Args:
        argv: Optional command-line arguments excluding executable name.

    Returns:
        Process status.
    """

    args = build_parser().parse_args(argv)
    try:
        profile = load_executable_profile(args.root)
        identity = load_keycloak_identity(profile)
        print("Keycloak site-profile reconciliation")
        print("------------------------------------")
        print(f"  Profile:         {profile.config_id}")
        print(f"  Server:          {identity.server_url}")
        print(f"  Realm:           {identity.realm}")
        print(f"  Frontend client: {identity.frontend_client_id}")
        print(f"  Backend client:  {identity.backend_client_id}")
        print(f"  Docker secret:   {identity.docker_secret}")
        print("")
        password = getpass.getpass(
            f"Keycloak admin password for {args.admin_user}: "
        )
        if not password:
            raise KeycloakProfileError(
                "Keycloak admin password is required."
            )
        summary = reconcile(
            profile,
            args.admin_user,
            password,
            replace_secret=args.replace_secret,
        )
        password = ""
        print("")
        print("Reconciliation completed:")
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    except (
        ExecutableProfileError,
        KeycloakProfileError,
        KeycloakRoleError,
        KeycloakSecretBridgeError,
        OSError,
    ) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "KeycloakAdminClient",
    "KeycloakIdentity",
    "KeycloakProfileError",
    "_backend_payload",
    "_frontend_payload",
    "ensure_audience_mapper",
    "ensure_client",
    "ensure_realm",
    "get_client_secret",
    "load_keycloak_identity",
    "main",
    "reconcile",
    "regenerate_client_secret",
]
