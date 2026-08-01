"""
Module: keycloak_profile_bootstrap_cli.py

Description:
    Owns the executable entry point for site-profile Keycloak bootstrap. It
    keeps interactive review, authentication, confirmation, optional secret
    recovery viewing, and completion reporting outside the reconciliation
    coordinator.

Dependencies:
    - Python standard library.
    - Executable profile and Keycloak bootstrap/CLI modules.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path

from executable_profile import (
    ExecutableProfile,
    ExecutableProfileError,
    load_executable_profile,
)
from keycloak_profile_application_access import KeycloakApplicationAccessError
from keycloak_profile_bootstrap import reconcile_authenticated
from keycloak_profile_cli import (
    authenticate_and_plan,
    confirm_apply,
    print_completion,
    print_plan,
    print_target,
    prompt_admin_user,
    prompt_bootstrap_test_user_passwords,
    prompt_bootstrap_values,
    prompt_secret_safe_debug,
)
from keycloak_profile_client import (
    KeycloakAdminClient,
    KeycloakIdentity,
    KeycloakProfileError,
    load_keycloak_identity,
)
from keycloak_profile_configuration import persist_keycloak_values
from keycloak_profile_roles import KeycloakRoleError
from keycloak_profile_secret_bridge import KeycloakSecretBridgeError
from keycloak_profile_secret_viewer import (
    KeycloakSecretViewerError,
    offer_temporary_secret_view,
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
        help=(
            "Apply the displayed sanitized plan without interactive approval "
            "and skip the optional one-time secret view."
        ),
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
    prior_identity = identity
    profile, changed = persist_keycloak_values(profile, selected_values)
    persisted_identity = load_keycloak_identity(profile) if changed else identity
    if changed:
        print(
            "\n[OK] Saved Keycloak deployment values to "
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
            persisted_identity.realm != prior_identity.realm
            or persisted_identity.backend_client_id
            != prior_identity.backend_client_id
        ):
            print(
                "[WARN] An existing Docker client secret belongs to the prior "
                "realm/backend client and requires explicit rotation with the "
                "stack stopped."
            )
    identity = selected_values.apply_access_selection(persisted_identity)
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
    """Collect runtime passwords, confirm, apply, and offer secret recovery.

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
        KeycloakSecretViewerError: If an accepted recovery view cannot be
            created or cleaned up safely.
    """

    passwords = prompt_bootstrap_test_user_passwords(identity, plan)
    if not confirm_apply(args.yes):
        passwords.clear()
        print("Keycloak bootstrap cancelled; no changes were applied.")
        return None
    print("")
    print("Applying and verifying")
    print("----------------------")
    secret_observer = None if args.yes else offer_temporary_secret_view
    try:
        return reconcile_authenticated(
            profile,
            client,
            replace_secret=args.replace_secret,
            docker_secret_present=docker_present,
            progress=print,
            bootstrap_test_user_passwords=passwords,
            secret_observer=secret_observer,
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
    except KeyboardInterrupt:
        print("\nKeycloak bootstrap cancelled; no further changes were applied.")
        return 130
    except (
        ExecutableProfileError,
        KeycloakProfileError,
        KeycloakApplicationAccessError,
        KeycloakRoleError,
        KeycloakSecretBridgeError,
        KeycloakSecretViewerError,
        OSError,
    ) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


__all__ = ["build_parser", "main"]
