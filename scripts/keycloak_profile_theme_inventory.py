"""
Module: keycloak_profile_theme_inventory.py

Description:
    Reads and normalizes the installed Keycloak theme inventory after an
    administrator has authenticated, then provides the interactive
    single-choice menus. Both selection and reconciliation safety consume this
    one source of live truth.

Dependencies:
    - Python standard library.
    - scripts/keycloak_profile_client.py.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from keycloak_profile_client import KeycloakAdminClient, KeycloakProfileError
from keycloak_profile_realm_configuration import (
    DEFAULT_THEME,
    KeycloakThemeSettings,
)


THEME_TYPES = ("login", "account", "admin", "email")


def _theme_names(
    server_info: Mapping[str, Any],
    theme_type: str,
) -> tuple[str, ...]:
    """Extract sorted installed names for one Keycloak theme category.

    Args:
        server_info: Keycloak server-info representation.
        theme_type: Theme category such as ``login`` or ``email``.

    Returns:
        Unique installed theme names sorted case-insensitively.

    Raises:
        KeycloakProfileError: If the live response omits or malforms the
            requested category.
    """

    themes = server_info.get("themes")
    if not isinstance(themes, Mapping):
        raise KeycloakProfileError(
            "Keycloak server information did not expose a theme inventory."
        )
    raw_items = themes.get(theme_type)
    if not isinstance(raw_items, list):
        raise KeycloakProfileError(
            f"Keycloak server information did not expose {theme_type} themes."
        )
    names: set[str] = set()
    for item in raw_items:
        if isinstance(item, str) and item:
            names.add(item)
        elif isinstance(item, Mapping):
            name = item.get("name")
            if isinstance(name, str) and name:
                names.add(name)
    if not names:
        raise KeycloakProfileError(
            f"Keycloak reported no installed {theme_type} themes."
        )
    return tuple(sorted(names, key=str.casefold))


def load_available_themes(
    client: KeycloakAdminClient,
) -> dict[str, tuple[str, ...]]:
    """Load every live Keycloak realm-theme category after authentication.

    Args:
        client: Authenticated Keycloak Admin client.

    Returns:
        Installed theme names keyed by login, account, admin, and email.

    Raises:
        KeycloakProfileError: If server information is unavailable or any
            required category is missing or malformed.
    """

    _, payload = client.request("GET", "/admin/serverinfo")
    if not isinstance(payload, Mapping):
        raise KeycloakProfileError(
            "Keycloak server theme inventory returned invalid data."
        )
    return {
        theme_type: _theme_names(payload, theme_type)
        for theme_type in THEME_TYPES
    }


def _prompt_theme_choice(
    label: str,
    current: str,
    available: tuple[str, ...],
) -> str:
    """Select one theme from the authenticated live server inventory.

    Args:
        label: Human-readable Keycloak theme category.
        current: Active deployment selection.
        available: Installed theme names returned by Keycloak.

    Returns:
        ``default`` or one installed theme name.
    """

    choices = (DEFAULT_THEME,) + tuple(
        name for name in available if name != DEFAULT_THEME
    )
    default_index = choices.index(current) + 1 if current in choices else None
    print("")
    print(f"{label} theme")
    for index, name in enumerate(choices, start=1):
        description = (
            "inherit server default"
            if name == DEFAULT_THEME
            else "installed"
        )
        current_note = " (current)" if name == current else ""
        print(f"  {index}) {name} - {description}{current_note}")
    if default_index is None:
        print(
            f"[WARN] Current selection {current!r} is not installed; "
            "choose an available value."
        )
    while True:
        default_hint = f" [{default_index}]" if default_index else ""
        answer = input(f"Select {label.lower()} theme{default_hint}: ").strip()
        if not answer and default_index is not None:
            return choices[default_index - 1]
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1]
        print(f"Please enter a number from 1 to {len(choices)}.")


def prompt_live_theme_settings(
    client: KeycloakAdminClient,
    current: KeycloakThemeSettings,
) -> KeycloakThemeSettings:
    """Load installed themes after login and collect all realm selections.

    Args:
        client: Authenticated Keycloak Admin client.
        current: Active deployment theme selections.

    Returns:
        Operator-selected settings containing only live choices or ``default``.

    Raises:
        KeycloakProfileError: If Keycloak does not expose a complete live theme
            inventory.
    """

    print("")
    print("Loading installed Keycloak themes...")
    inventory = load_available_themes(client)
    print("")
    print("Realm themes")
    print("------------")
    print("Choose from themes reported by the authenticated Keycloak server.")
    print("Press Enter to keep the numbered current selection.")
    return KeycloakThemeSettings(
        login=_prompt_theme_choice(
            "Login",
            current.login,
            inventory["login"],
        ),
        account=_prompt_theme_choice(
            "Account",
            current.account,
            inventory["account"],
        ),
        admin=_prompt_theme_choice(
            "Admin",
            current.admin,
            inventory["admin"],
        ),
        email=_prompt_theme_choice(
            "Email",
            current.email,
            inventory["email"],
        ),
    )


__all__ = [
    "THEME_TYPES",
    "load_available_themes",
    "prompt_live_theme_settings",
]
