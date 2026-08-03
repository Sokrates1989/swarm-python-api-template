"""
Module: keycloak_profile_auth_dialog.py

Description:
    Owns the first interactive boundary of profile-driven Keycloak bootstrap.
    It repeatedly verifies an administrator login and Admin API access before
    any realm configuration question is shown. Operators may explicitly skip
    the complete bootstrap without turning a cancelled login into a failure.

Dependencies:
    - Python standard library.
    - scripts/keycloak_profile_client.py.
"""

from __future__ import annotations

import getpass

from keycloak_profile_client import (
    KeycloakAdminClient,
    KeycloakIdentity,
    KeycloakProfileError,
)


SKIP_WORDS = {"q", "quit", "skip", "abort", "cancel"}


def _read_admin_username(default: str) -> str | None:
    """Read an administrator username or an explicit bootstrap skip.

    Args:
        default: Username selected when the operator presses Enter.

    Returns:
        The selected username, or ``None`` when the operator enters a
        documented skip word or interrupts credential input.
    """

    try:
        answer = input(
            f"Keycloak admin username [{default}] (q = skip bootstrap): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if answer.lower() in SKIP_WORDS:
        return None
    return answer or default


def _read_admin_password(username: str) -> str | None:
    """Read one administrator password without terminal echo.

    Args:
        username: Administrator whose password is being requested.

    Returns:
        Entered password, an empty string for invalid empty input, or ``None``
        when credential entry is interrupted.
    """

    try:
        return getpass.getpass(
            f"Keycloak admin password for {username}: "
        )
    except (EOFError, KeyboardInterrupt):
        return None


def authenticate_admin_until_valid(
    identity: KeycloakIdentity,
    default_username: str = "admin",
) -> KeycloakAdminClient | None:
    """Authenticate and prove Admin API access until success or cancellation.

    The administrator username and password are the first interactive
    questions in bootstrap. A token alone is insufficient evidence: the
    authenticated client must also read ``/admin/serverinfo`` before later
    realm, theme, locale, email, role, or user questions are allowed.

    Args:
        identity: Profile-derived trust anchor and current realm identity.
        default_username: Initial Enter-default administrator username.

    Returns:
        Verified authenticated client, or ``None`` when the operator skips or
        interrupts this bootstrap attempt.
    """

    active_default = default_username or "admin"
    print("")
    print("Keycloak administrator authentication")
    print("--------------------------------------")
    print(f"Server: {identity.server_url}")
    print("Credentials are verified before any realm configuration questions.")
    print(
        "Enter q at the username prompt, or press Ctrl+C, to set up "
        "Keycloak later."
    )
    while True:
        username = _read_admin_username(active_default)
        if username is None:
            return None
        password = _read_admin_password(username)
        if password is None:
            return None
        if not password:
            print("[WARN] The Keycloak admin password cannot be empty.")
            print("Try again, or enter q at the username prompt to skip.")
            active_default = username
            continue
        print("\nAuthenticating and verifying Keycloak Admin API access...")
        try:
            client = KeycloakAdminClient(
                identity,
                username,
                password,
                debug=False,
            )
            client.request("GET", "/admin/serverinfo")
        except KeycloakProfileError as error:
            print(f"[WARN] Keycloak administrator verification failed: {error}")
            print("Try again, or enter q at the username prompt to skip.")
            active_default = username
            continue
        finally:
            password = ""
        print(f"[OK] Authenticated Keycloak administrator {username!r}.")
        return client


__all__ = ["authenticate_admin_until_valid"]
