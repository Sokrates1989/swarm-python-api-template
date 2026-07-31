"""
Module: keycloak_profile_bootstrap.py

Description:
    Coordinates generic, site-profile-driven Keycloak reconciliation against
    an existing server and bridges the confidential backend credential to its
    declared Docker secret. No application identity or Keycloak deployment
    path is embedded here.

Dependencies:
    - Python standard library.
    - Executable profile, Keycloak CLI/client/reconciliation/role/verification,
      and Docker secret bridge modules.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

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
from keycloak_profile_cli import (
    authenticate_and_plan,
    confirm_apply,
    print_completion,
    print_plan,
    print_target,
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
from keycloak_profile_verification import (
    build_reconciliation_plan,
    verify_reconciled_state,
)


def _preflight_secret_state(
    profile: ExecutableProfile,
    identity: KeycloakIdentity,
    client: KeycloakAdminClient,
    *,
    docker_secret_present: bool,
    replace_secret: bool,
) -> tuple[bool, bool]:
    """Check stack, backend-client, and Docker-secret state before client writes.

    Args:
        profile: Active executable site profile.
        identity: Profile-derived Keycloak identity.
        client: Authenticated Keycloak Admin client.
        docker_secret_present: Fresh Docker inspection result.
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
    docker_present = docker_secret_present
    if backend_missing and docker_present and not replace_secret:
        raise KeycloakProfileError(
            "The backend Keycloak client is missing while its Docker secret "
            "already exists. Use explicit secret rotation after confirming "
            "the selected stack is stopped."
        )
    return backend_missing, docker_present


def _require_rotation_stack_stopped(
    profile: ExecutableProfile,
    *,
    replace_secret: bool,
) -> None:
    """Reject live-stack rotation before any Keycloak mutation.

    Args:
        profile: Active executable site profile.
        replace_secret: Whether explicit credential rotation was requested.

    Returns:
        Nothing when rotation is not requested or the stack is stopped.

    Raises:
        KeycloakProfileError: If the selected stack is still running.
        KeycloakSecretBridgeError: If Docker stack state cannot be inspected.
    """

    if replace_secret and stack_is_running(profile.stack_name):
        raise KeycloakProfileError(
            "Stop the selected stack before rotating its Keycloak client secret."
        )


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
        return "present-unverified"
    if replace_secret and backend_action != "created":
        secret = regenerate_client_secret(client, backend_uuid)
    else:
        secret = get_client_secret(client, backend_uuid)
    try:
        client.prove_client_credentials(
            identity.backend_client_id,
            secret,
        )
        return write_docker_secret(
            profile,
            identity,
            secret,
            replace=replace_secret,
        )
    finally:
        secret = ""


def _report(
    progress: Callable[[str], None] | None,
    message: str,
) -> None:
    """Emit one optional operator progress message.

    Args:
        progress: Optional output callback.
        message: Secret-free status text.

    Returns:
        Nothing.
    """

    if progress is not None:
        progress(message)


def _require_applicable_plan(
    client: KeycloakAdminClient,
    *,
    docker_secret_present: bool,
    replace_secret: bool,
) -> None:
    """Reject live-state blockers before the first mutation.

    Args:
        client: Authenticated Keycloak Admin client.
        docker_secret_present: Whether the declared Docker secret exists.
        replace_secret: Whether explicit rotation was requested.

    Returns:
        Nothing when the sanitized plan has no blockers.

    Raises:
        KeycloakProfileError: If profile-forbidden state is present.
    """

    plan = build_reconciliation_plan(
        client,
        docker_secret_present=docker_secret_present,
        replace_secret=replace_secret,
    )
    if plan["blockers"]:
        raise KeycloakProfileError(
            "Keycloak apply is blocked: " + "; ".join(plan["blockers"])
        )


def _apply_and_verify_keycloak(
    client: KeycloakAdminClient,
    identity: KeycloakIdentity,
    realm_action: str,
    progress: Callable[[str], None] | None,
) -> tuple[str, str, str, str, str, str]:
    """Apply every declared Keycloak component and verify observed state.

    Args:
        client: Authenticated Keycloak Admin client.
        identity: Profile-derived Keycloak identity.
        realm_action: Already completed realm action.
        progress: Optional secret-free progress callback.

    Returns:
        Realm, frontend, backend, mapper, and role actions plus backend UUID.

    Raises:
        KeycloakProfileError: If reconciliation or verification fails.
        KeycloakRoleError: If service-account role state is unsafe.
    """

    _report(progress, "[2/7] Reconciling public PKCE frontend client...")
    (
        _,
        frontend_action,
        backend_uuid,
        backend_action,
        mapper_action,
        roles_action,
    ) = _reconcile_clients(client, identity)
    _report(progress, f"      Frontend client: {frontend_action}")
    _report(progress, f"[3/7] Backend service client: {backend_action}")
    _report(progress, f"[4/7] Audience mapper: {mapper_action}")
    _report(progress, f"[5/7] Service-account roles: {roles_action}")
    _report(progress, "[6/7] Verifying Admin API state, issuer, and JWKS...")
    verify_reconciled_state(client)
    _report(progress, "      Keycloak state verification: passed")
    return (
        realm_action,
        frontend_action,
        backend_action,
        mapper_action,
        roles_action,
        backend_uuid,
    )


def _report_secret_bridge(
    progress: Callable[[str], None] | None,
    binding_verified: bool,
) -> None:
    """Report secret-bridge proof without exposing credential material.

    Args:
        progress: Optional secret-free progress callback.
        binding_verified: Whether this run proved and wrote the same value.

    Returns:
        Nothing.
    """

    if binding_verified:
        _report(
            progress,
            "      Keycloak generated, returned, and accepted the credential; "
            "the same in-memory value was sent to Docker.",
        )
        return
    _report(
        progress,
        "      Existing Docker secret kept; Docker does not expose its "
        "value, so the binding cannot be re-proved.",
    )


def _build_summary(
    profile: ExecutableProfile,
    identity: KeycloakIdentity,
    actions: tuple[str, str, str, str, str, str],
    docker_action: str,
    binding_verified: bool,
) -> dict[str, object]:
    """Build the final secret-free reconciliation result.

    Args:
        profile: Active executable profile.
        identity: Profile-derived Keycloak identity.
        actions: Realm, frontend, backend, mapper, role actions and backend UUID.
        docker_action: Docker secret bridge action.
        binding_verified: Whether the secret was proven and written this run.

    Returns:
        JSON-compatible summary without credentials.
    """

    realm, frontend, backend, mapper, roles, _ = actions
    return {
        "profile": profile.config_id,
        "realm": identity.realm,
        "realmAction": realm,
        "frontendClient": identity.frontend_client_id,
        "frontendAction": frontend,
        "backendClient": identity.backend_client_id,
        "backendAction": backend,
        "audience": identity.audience,
        "audienceMapperAction": mapper,
        "serviceAccountRolesAction": roles,
        "dockerSecret": identity.docker_secret,
        "dockerSecretAction": docker_action,
        "keycloakStateVerified": True,
        "dockerSecretBindingVerified": binding_verified,
    }


def reconcile_authenticated(
    profile: ExecutableProfile,
    client: KeycloakAdminClient,
    *,
    replace_secret: bool,
    docker_secret_present: bool | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Reconcile and verify state through one authenticated Admin client.

    Args:
        profile: Active executable profile.
        client: Authenticated Keycloak Admin client.
        replace_secret: Rotate and replace the client secret when true.
        docker_secret_present: Optional preflight result reused from planning.
        progress: Optional secret-free progress callback.

    Returns:
        Secret-free action summary.

    Raises:
        KeycloakProfileError: If Keycloak state is unsafe or unavailable.
        KeycloakRoleError: If service-account roles exceed the declaration.
        KeycloakSecretBridgeError: If Docker state is unsafe or unavailable.
    """

    identity = client.identity
    current_docker_state = docker_secret_exists(identity.docker_secret)
    if (
        docker_secret_present is not None
        and docker_secret_present != current_docker_state
    ):
        raise KeycloakProfileError(
            "Docker secret state changed after the displayed plan; rerun "
            "Keycloak bootstrap."
        )
    docker_secret_present = current_docker_state
    _require_applicable_plan(
        client,
        docker_secret_present=docker_secret_present,
        replace_secret=replace_secret,
    )
    _require_rotation_stack_stopped(
        profile,
        replace_secret=replace_secret,
    )
    _report(progress, "[1/7] Reconciling realm settings...")
    realm_action = ensure_realm(client)
    _report(progress, f"      Realm: {realm_action}")
    _, docker_present = _preflight_secret_state(
        profile,
        identity,
        client,
        docker_secret_present=docker_secret_present,
        replace_secret=replace_secret,
    )
    actions = _apply_and_verify_keycloak(
        client,
        identity,
        realm_action,
        progress,
    )
    backend_action = actions[2]
    backend_uuid = actions[5]
    _report(progress, "[7/7] Reconciling the Docker client-secret bridge...")
    docker_action = _bridge_client_secret(
        profile,
        identity,
        client,
        backend_uuid,
        backend_action,
        docker_secret_present=docker_present,
        replace_secret=replace_secret,
    )
    binding_verified = docker_action in {"created", "replaced"}
    _report_secret_bridge(progress, binding_verified)
    return _build_summary(
        profile,
        identity,
        actions,
        docker_action,
        binding_verified,
    )


def reconcile(
    profile: ExecutableProfile,
    admin_user: str,
    admin_password: str,
    *,
    replace_secret: bool,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Authenticate, reconcile, and strictly verify the selected profile.

    Args:
        profile: Active executable profile.
        admin_user: Existing Keycloak administrator username.
        admin_password: Administrator password retained only in memory.
        replace_secret: Rotate and replace the client secret when true.
        progress: Optional secret-free progress callback.

    Returns:
        Secret-free action and verification summary.

    Raises:
        KeycloakProfileError: If Keycloak state is unsafe or unavailable.
        KeycloakRoleError: If service-account roles exceed the declaration.
        KeycloakSecretBridgeError: If Docker state is unsafe or unavailable.
    """

    identity = load_keycloak_identity(profile)
    client = KeycloakAdminClient(identity, admin_user, admin_password)
    return reconcile_authenticated(
        profile,
        client,
        replace_secret=replace_secret,
        progress=progress,
    )


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
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Apply the displayed sanitized plan without an interactive prompt.",
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
        print_target(profile, identity)
        client, docker_present, plan = authenticate_and_plan(
            identity,
            args.admin_user,
            replace_secret=args.replace_secret,
        )
        print_plan(plan)
        if plan["blockers"]:
            raise KeycloakProfileError(
                "Resolve every displayed blocker before bootstrap."
            )
        if not confirm_apply(args.yes):
            print("Keycloak bootstrap cancelled; no changes were applied.")
            return 0
        print("")
        print("Applying and verifying")
        print("----------------------")
        summary = reconcile_authenticated(
            profile,
            client,
            replace_secret=args.replace_secret,
            docker_secret_present=docker_present,
            progress=print,
        )
        print_completion(identity, summary)
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
    "reconcile_authenticated",
    "regenerate_client_secret",
]
