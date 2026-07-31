"""
Module: keycloak_profile_bootstrap.py

Description:
    Coordinates generic, site-profile-driven Keycloak reconciliation against
    an existing server and bridges the confidential backend credential to its
    declared Docker secret. No application identity or Keycloak deployment
    path is embedded here.

Dependencies:
    - Python standard library.
    - Executable profile, Keycloak CLI/client/configuration/reconciliation,
      application-access, role-scope, service-account role/verification, and
      Docker secret bridge modules.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Callable

from executable_profile import (
    ExecutableProfile,
    ExecutableProfileError,
    load_executable_profile,
)
from keycloak_profile_configuration import persist_keycloak_values
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
    prompt_admin_user,
    prompt_bootstrap_values,
    prompt_bootstrap_test_user_passwords,
    prompt_secret_safe_debug,
)
from keycloak_profile_application_access import (
    KeycloakApplicationAccessError,
    ensure_bootstrap_test_users,
    ensure_realm_roles,
)
from keycloak_profile_realm_role_scope import (
    ensure_frontend_realm_role_scope,
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
    build_client_secret_value_evidence,
    build_opaque_client_secret_value_evidence,
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
) -> tuple[str, str, str, str, str, str, str]:
    """Reconcile both clients, audience mapper, and exact service-account roles.

    Args:
        client: Authenticated Keycloak Admin client.
        identity: Profile-derived Keycloak identity.

    Returns:
        Frontend UUID/action, backend UUID/action, mapper action, frontend
        realm-role scope action, and service-account role action.

    Raises:
        KeycloakProfileError: If client or mapper reconciliation fails.
        KeycloakApplicationAccessError: If frontend application-role scope is
            malformed or cannot be reconciled.
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
    frontend_role_scope_action = ensure_frontend_realm_role_scope(
        client,
        frontend_uuid,
    )
    roles_action = ensure_service_account_roles(client, backend_uuid)
    return (
        frontend_uuid,
        frontend_action,
        backend_uuid,
        backend_action,
        mapper_action,
        frontend_role_scope_action,
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
) -> tuple[str, dict[str, object]]:
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
        Docker secret action and secret-safe value evidence.

    Raises:
        KeycloakProfileError: If Keycloak omits the credential.
        KeycloakSecretBridgeError: If Docker cannot create or replace it.
    """

    if docker_secret_present and not replace_secret:
        return (
            "present-unverified",
            build_opaque_client_secret_value_evidence(),
        )
    if replace_secret and backend_action != "created":
        secret = regenerate_client_secret(client, backend_uuid)
    else:
        secret = get_client_secret(client, backend_uuid)
    try:
        evidence = build_client_secret_value_evidence(
            secret,
            identity.docker_secret,
        )
        client.prove_client_credentials(
            identity.backend_client_id,
            secret,
        )
        action = write_docker_secret(
            profile,
            identity,
            secret,
            replace=replace_secret,
        )
        return action, evidence
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
    bootstrap_test_user_passwords: Mapping[str, str],
    progress: Callable[[str], None] | None,
) -> tuple[str, str, str, str, str, str, str, str, str]:
    """Apply every declared Keycloak component and verify observed state.

    Args:
        client: Authenticated Keycloak Admin client.
        identity: Profile-derived Keycloak identity.
        realm_action: Already completed realm action.
        bootstrap_test_user_passwords: Runtime-only passwords for users needing
            creation or password-credential recovery.
        progress: Optional secret-free progress callback.

    Returns:
        Realm, application-role, frontend, backend, mapper, service-account
        role, and test-user actions plus backend UUID.

    Raises:
        KeycloakProfileError: If reconciliation or verification fails.
        KeycloakApplicationAccessError: If application role, role-scope, or
            temporary-user state cannot be reconciled and verified.
        KeycloakRoleError: If service-account role state is unsafe.
    """

    _report(progress, "[2/10] Reconciling application realm roles...")
    realm_roles_action = ensure_realm_roles(client)
    _report(progress, f"      Application realm roles: {realm_roles_action}")
    _report(progress, "[3/10] Reconciling public PKCE frontend client...")
    (
        _,
        frontend_action,
        backend_uuid,
        backend_action,
        mapper_action,
        frontend_role_scope_action,
        roles_action,
    ) = _reconcile_clients(client, identity)
    _report(progress, f"      Frontend client: {frontend_action}")
    _report(progress, f"[4/10] Backend service client: {backend_action}")
    _report(progress, f"[5/10] Audience mapper: {mapper_action}")
    _report(
        progress,
        f"[6/10] Frontend application-role scope: {frontend_role_scope_action}",
    )
    _report(progress, f"[7/10] Service-account roles: {roles_action}")
    _report(progress, "[8/10] Reconciling temporary bootstrap test users...")
    test_users_action = ensure_bootstrap_test_users(
        client,
        bootstrap_test_user_passwords,
    )
    _report(progress, f"      Bootstrap test users: {test_users_action}")
    _report(progress, "[9/10] Verifying Admin API state, issuer, and JWKS...")
    verify_reconciled_state(client)
    _report(progress, "      Keycloak state verification: passed")
    return (
        realm_action,
        realm_roles_action,
        frontend_action,
        backend_action,
        mapper_action,
        frontend_role_scope_action,
        roles_action,
        test_users_action,
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
    actions: tuple[str, str, str, str, str, str, str, str, str],
    docker_action: str,
    binding_verified: bool,
    secret_value_evidence: dict[str, object],
) -> dict[str, object]:
    """Build the final secret-free reconciliation result.

    Args:
        profile: Active executable profile.
        identity: Profile-derived Keycloak identity.
        actions: Realm, application-role, frontend, backend, mapper, frontend
            role-scope, service-account role, and test-user actions plus UUID.
        docker_action: Docker secret bridge action.
        binding_verified: Whether the secret was proven and written this run.
        secret_value_evidence: One-way credential observation evidence.

    Returns:
        JSON-compatible summary without credentials.
    """

    (
        realm,
        realm_roles,
        frontend,
        backend,
        mapper,
        frontend_role_scope,
        roles,
        test_users,
        _,
    ) = actions
    return {
        "profile": profile.config_id,
        "realm": identity.realm,
        "realmAction": realm,
        "realmRolesAction": realm_roles,
        "frontendClient": identity.frontend_client_id,
        "frontendAction": frontend,
        "backendClient": identity.backend_client_id,
        "backendAction": backend,
        "audience": identity.audience,
        "audienceMapperAction": mapper,
        "frontendRealmRoleScopeAction": frontend_role_scope,
        "serviceAccountRolesAction": roles,
        "bootstrapTestUsersAction": test_users,
        "dockerSecretName": identity.docker_secret,
        "dockerSecretAction": docker_action,
        "keycloakStateVerified": True,
        "dockerSecretBindingVerified": binding_verified,
        "clientSecretValueEvidence": secret_value_evidence,
    }


def _current_docker_secret_state(
    identity: KeycloakIdentity,
    planned_state: bool | None,
) -> bool:
    """Read Docker secret state and reject changes since planning.

    Args:
        identity: Active profile-derived Keycloak identity.
        planned_state: Optional state captured for the displayed plan.

    Returns:
        Current Docker-secret presence.

    Raises:
        KeycloakProfileError: If state changed after the displayed plan.
        KeycloakSecretBridgeError: If Docker inspection fails.
    """

    current = docker_secret_exists(identity.docker_secret)
    if planned_state is not None and planned_state != current:
        raise KeycloakProfileError(
            "Docker secret state changed after the displayed plan; rerun "
            "Keycloak bootstrap."
        )
    return current


def _bridge_reconciled_secret(
    profile: ExecutableProfile,
    identity: KeycloakIdentity,
    client: KeycloakAdminClient,
    actions: tuple[str, str, str, str, str, str, str, str, str],
    *,
    docker_secret_present: bool,
    replace_secret: bool,
    progress: Callable[[str], None] | None,
) -> tuple[str, bool, dict[str, object]]:
    """Bridge the reconciled backend credential and report proof state.

    Args:
        profile: Active executable profile.
        identity: Active profile-derived Keycloak identity.
        client: Authenticated Keycloak Admin client.
        actions: Completed Keycloak reconciliation actions and backend UUID.
        docker_secret_present: Current Docker-secret presence.
        replace_secret: Whether explicit rotation was requested.
        progress: Optional secret-free progress callback.

    Returns:
        Docker action, whether this run proved the exact stored binding, and
        one-way client-secret value evidence.

    Raises:
        KeycloakProfileError: If Keycloak cannot provide or prove a credential.
        KeycloakSecretBridgeError: If Docker cannot write the credential.
    """

    _report(progress, "[10/10] Reconciling the Docker client-secret bridge...")
    docker_action, secret_value_evidence = _bridge_client_secret(
        profile,
        identity,
        client,
        actions[8],
        actions[3],
        docker_secret_present=docker_secret_present,
        replace_secret=replace_secret,
    )
    binding_verified = docker_action in {"created", "replaced"}
    _report_secret_bridge(progress, binding_verified)
    return docker_action, binding_verified, secret_value_evidence


def _prepare_keycloak_apply(
    profile: ExecutableProfile,
    client: KeycloakAdminClient,
    *,
    planned_docker_state: bool | None,
    replace_secret: bool,
    progress: Callable[[str], None] | None,
) -> tuple[KeycloakIdentity, bool, str]:
    """Revalidate the plan boundary and reconcile realm state first.

    Args:
        profile: Active executable profile.
        client: Authenticated Keycloak Admin client.
        planned_docker_state: Optional state captured for the displayed plan.
        replace_secret: Whether explicit rotation was requested.
        progress: Optional secret-free progress callback.

    Returns:
        Active identity, current Docker-secret presence, and realm action.

    Raises:
        KeycloakProfileError: If the plan is blocked or state changed.
        KeycloakApplicationAccessError: If the plan finds malformed
            application role or temporary-user state.
        KeycloakRoleError: If live service-account roles are unsafe.
        KeycloakSecretBridgeError: If Docker state cannot be inspected.
    """

    identity = client.identity
    docker_present = _current_docker_secret_state(
        identity,
        planned_docker_state,
    )
    _require_applicable_plan(
        client,
        docker_secret_present=docker_present,
        replace_secret=replace_secret,
    )
    _require_rotation_stack_stopped(profile, replace_secret=replace_secret)
    _report(progress, "[1/10] Reconciling realm settings...")
    realm_action = ensure_realm(client)
    _report(progress, f"      Realm: {realm_action}")
    return identity, docker_present, realm_action


def reconcile_authenticated(
    profile: ExecutableProfile,
    client: KeycloakAdminClient,
    *,
    replace_secret: bool,
    docker_secret_present: bool | None = None,
    progress: Callable[[str], None] | None = None,
    bootstrap_test_user_passwords: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Reconcile and verify state through one authenticated Admin client.

    Args:
        profile: Active executable profile.
        client: Authenticated Keycloak Admin client.
        replace_secret: Rotate and replace the client secret when true.
        docker_secret_present: Optional preflight result reused from planning.
        progress: Optional secret-free progress callback.
        bootstrap_test_user_passwords: Runtime-only passwords keyed by test
            usernames requiring creation or credential recovery.

    Returns:
        Secret-free action summary.

    Raises:
        KeycloakProfileError: If Keycloak state is unsafe or unavailable.
        KeycloakApplicationAccessError: If application role or user state is
            unsafe or cannot be verified.
        KeycloakRoleError: If service-account roles exceed the declaration.
        KeycloakSecretBridgeError: If Docker state is unsafe or unavailable.
    """

    identity, docker_secret_present, realm_action = _prepare_keycloak_apply(
        profile,
        client,
        planned_docker_state=docker_secret_present,
        replace_secret=replace_secret,
        progress=progress,
    )
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
        bootstrap_test_user_passwords or {},
        progress,
    )
    (
        docker_action,
        binding_verified,
        secret_value_evidence,
    ) = _bridge_reconciled_secret(
        profile,
        identity,
        client,
        actions,
        docker_secret_present=docker_present,
        replace_secret=replace_secret,
        progress=progress,
    )
    return _build_summary(
        profile,
        identity,
        actions,
        docker_action,
        binding_verified,
        secret_value_evidence,
    )


def reconcile(
    profile: ExecutableProfile,
    admin_user: str,
    admin_password: str,
    *,
    replace_secret: bool,
    progress: Callable[[str], None] | None = None,
    bootstrap_test_user_passwords: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Authenticate, reconcile, and strictly verify the selected profile.

    Args:
        profile: Active executable profile.
        admin_user: Existing Keycloak administrator username.
        admin_password: Administrator password retained only in memory.
        replace_secret: Rotate and replace the client secret when true.
        progress: Optional secret-free progress callback.
        bootstrap_test_user_passwords: Runtime-only passwords for test-user
            creation or credential recovery. Interactive callers collect these
            after the live plan.

    Returns:
        Secret-free action and verification summary.

    Raises:
        KeycloakProfileError: If Keycloak state is unsafe or unavailable.
        KeycloakApplicationAccessError: If application role or user state is
            unsafe or cannot be verified.
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
        bootstrap_test_user_passwords=bootstrap_test_user_passwords,
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
        default=None,
        help=(
            "Existing Keycloak administrator username. When omitted, the "
            "interactive prompt follows the complete target summary."
        ),
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
    parser.add_argument(
        "--accept-profile-values",
        action="store_true",
        help=(
            "Accept the already validated public site-profile values without "
            "the interactive value-by-value review."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Print secret-safe Admin API method/path/query-key/status traces. "
            "Bodies, headers, query values, and credentials remain hidden."
        ),
    )
    return parser


def _review_bootstrap_configuration(
    profile: ExecutableProfile,
    identity: KeycloakIdentity,
    *,
    skip_review: bool,
) -> tuple[ExecutableProfile, KeycloakIdentity]:
    """Collect, persist, and redisplay changed public Keycloak values.

    Args:
        profile: Current validated deployment profile.
        identity: Current normalized Keycloak identity.
        skip_review: Keep existing values without interactive questions.

    Returns:
        Active profile and identity after optional persistence and rendering.

    Raises:
        ExecutableProfileError: If entered values or stack rendering fail.
        KeycloakProfileError: If the server trust anchor is changed.
        OSError: If generated deployment artifacts cannot be replaced.
    """

    if skip_review:
        return profile, identity
    selected_values = prompt_bootstrap_values(identity)
    profile, changed = persist_keycloak_values(profile, selected_values)
    if not changed:
        return profile, identity
    prior_identity = identity
    identity = load_keycloak_identity(profile)
    print("")
    print(
        "[OK] Saved Keycloak deployment values to "
        f"{profile.root / '.env'}"
    )
    print(
        "[OK] Rebuilt generated stack at "
        f"{profile.root / 'swarm-stack.yml'}"
    )
    print(
        "[WARN] WebApp/mobile artifacts must be built with this "
        "realm and client identity."
    )
    if (
        identity.realm != prior_identity.realm
        or identity.backend_client_id != prior_identity.backend_client_id
    ):
        print(
            "[WARN] An existing Docker client secret belongs to the prior "
            "realm/backend client and requires explicit rotation with the "
            "stack stopped."
        )
    print("")
    print_target(profile, identity)
    return profile, identity


def _apply_interactive_plan(
    profile: ExecutableProfile,
    identity: KeycloakIdentity,
    client: KeycloakAdminClient,
    plan: Mapping[str, object],
    docker_present: bool,
    args: argparse.Namespace,
) -> dict[str, object] | None:
    """Collect runtime passwords, confirm, and apply one displayed plan.

    Args:
        profile: Active executable profile.
        identity: Active profile-derived Keycloak identity.
        client: Authenticated Keycloak Admin client used for the plan.
        plan: Sanitized live-state plan already shown to the operator.
        docker_present: Docker-secret state captured for that plan.
        args: Parsed CLI options controlling confirmation and rotation.

    Returns:
        Secret-free bootstrap summary, or ``None`` when cancelled.

    Raises:
        KeycloakProfileError: If runtime password collection or apply fails.
        KeycloakApplicationAccessError: If roles or users cannot reconcile.
        KeycloakRoleError: If service-account role state is unsafe.
        KeycloakSecretBridgeError: If Docker secret operations fail.
    """

    passwords = prompt_bootstrap_test_user_passwords(identity, plan)
    if not confirm_apply(args.yes):
        passwords.clear()
        print("Keycloak bootstrap cancelled; no changes were applied.")
        return None
    print("")
    print("Applying and verifying")
    print("----------------------")
    try:
        return reconcile_authenticated(
            profile,
            client,
            replace_secret=args.replace_secret,
            docker_secret_present=docker_present,
            progress=print,
            bootstrap_test_user_passwords=passwords,
        )
    finally:
        passwords.clear()


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
        profile, identity = _review_bootstrap_configuration(
            profile,
            identity,
            skip_review=args.accept_profile_values,
        )
        debug = args.debug
        if not args.accept_profile_values and not debug:
            debug = prompt_secret_safe_debug()
        admin_user = args.admin_user or prompt_admin_user()
        client, docker_present, plan = authenticate_and_plan(
            identity,
            admin_user,
            replace_secret=args.replace_secret,
            debug=debug,
        )
        print_plan(plan)
        if plan["blockers"]:
            raise KeycloakProfileError(
                "Resolve every displayed blocker before bootstrap."
            )
        summary = _apply_interactive_plan(
            profile,
            identity,
            client,
            plan,
            docker_present,
            args,
        )
        if summary is None:
            return 0
        print_completion(identity, summary)
        return 0
    except (
        ExecutableProfileError,
        KeycloakProfileError,
        KeycloakApplicationAccessError,
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
