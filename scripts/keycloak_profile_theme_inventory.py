"""
Module: keycloak_profile_theme_inventory.py

Description:
    Reads and normalizes installed Keycloak themes and their supported locales
    after an administrator has authenticated. It provides the interactive
    theme single-choice menus and the reusable installer-style realm-locale
    multiselect. Selection and reconciliation safety consume one live source
    of truth.

Dependencies:
    - Python standard library.
    - scripts/keycloak_profile_client.py.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from keycloak_profile_client import KeycloakAdminClient, KeycloakProfileError
from keycloak_profile_realm_configuration import (
    DEFAULT_THEME,
    KeycloakLocalizationSettings,
    KeycloakThemeSettings,
)
from terminal_multiselect import MultiselectOption, select_many


THEME_TYPES = ("login", "account", "admin", "email")
PromptBoolean = Callable[[str, bool], bool]


@dataclass(frozen=True)
class KeycloakThemeInfo:
    """Describe one installed theme returned by Keycloak server info.

    Attributes:
        name: Installed theme name accepted by realm configuration.
        locales: Locale identifiers reported as supported by this theme.
        description: Optional server-provided human-readable description.
    """

    name: str
    locales: tuple[str, ...]
    description: str = ""


def _theme_options(
    server_info: Mapping[str, Any],
    theme_type: str,
) -> tuple[KeycloakThemeInfo, ...]:
    """Extract installed theme metadata for one Keycloak category.

    Args:
        server_info: Keycloak server-info representation.
        theme_type: Theme category such as ``login`` or ``email``.

    Returns:
        Unique installed themes sorted case-insensitively by name.

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
    options: dict[str, KeycloakThemeInfo] = {}
    for item in raw_items:
        if isinstance(item, str) and item:
            options[item] = KeycloakThemeInfo(item, ())
        elif isinstance(item, Mapping):
            name = item.get("name")
            if isinstance(name, str) and name:
                raw_locales = item.get("locales", [])
                locales = ()
                if isinstance(raw_locales, list) and all(
                    isinstance(locale, str) and locale
                    for locale in raw_locales
                ):
                    locales = tuple(
                        sorted(set(raw_locales), key=str.casefold)
                    )
                description = item.get("description", "")
                options[name] = KeycloakThemeInfo(
                    name=name,
                    locales=locales,
                    description=(
                        description if isinstance(description, str) else ""
                    ),
                )
    if not options:
        raise KeycloakProfileError(
            f"Keycloak reported no installed {theme_type} themes."
        )
    return tuple(
        options[name] for name in sorted(options, key=str.casefold)
    )


def load_theme_inventory(
    client: KeycloakAdminClient,
) -> dict[str, tuple[KeycloakThemeInfo, ...]]:
    """Load installed theme names, descriptions, and locale metadata.

    Args:
        client: Authenticated Keycloak Admin client.

    Returns:
        Theme metadata keyed by login, account, admin, and email category.

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
        theme_type: _theme_options(payload, theme_type)
        for theme_type in THEME_TYPES
    }


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

    inventory = load_theme_inventory(client)
    return {
        theme_type: tuple(option.name for option in options)
        for theme_type, options in inventory.items()
    }


def _prompt_theme_choice(
    label: str,
    current: str,
    available: Sequence[KeycloakThemeInfo],
) -> str:
    """Select one theme from the authenticated live server inventory.

    Args:
        label: Human-readable Keycloak theme category.
        current: Active deployment selection.
        available: Installed theme metadata returned by Keycloak.

    Returns:
        ``default`` or one installed theme name.
    """

    choices = (DEFAULT_THEME,) + tuple(
        option.name
        for option in available
        if option.name != DEFAULT_THEME
    )
    default_index = choices.index(current) + 1 if current in choices else None
    print("")
    print(f"{label} theme")
    for index, name in enumerate(choices, start=1):
        matching = next(
            (option for option in available if option.name == name),
            None,
        )
        description = "inherit server default"
        if matching is not None:
            description = matching.description or "installed"
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


def _prompt_theme_settings(
    inventory: Mapping[str, Sequence[KeycloakThemeInfo]],
    current: KeycloakThemeSettings,
) -> KeycloakThemeSettings:
    """Collect all realm theme selections from one loaded inventory.

    Args:
        inventory: Live theme metadata keyed by required theme category.
        current: Active deployment theme selections.

    Returns:
        Operator-selected settings containing only live choices or ``default``.

    Raises:
        KeycloakProfileError: If the inventory omits a required category.
    """

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
        KeycloakProfileError: If Keycloak does not expose a complete live
            theme inventory.
    """

    print("")
    print("Loading installed Keycloak themes and locale support...")
    return _prompt_theme_settings(load_theme_inventory(client), current)


def _login_theme_locales(
    inventory: Mapping[str, Sequence[KeycloakThemeInfo]],
    selected_theme: str,
) -> tuple[str, ...]:
    """Resolve selectable locales from the selected live login theme.

    Args:
        inventory: Live theme metadata keyed by theme category.
        selected_theme: Explicit login theme name or ``default`` sentinel.

    Returns:
        Sorted locale identifiers. For inherited server defaults, the Admin
        API does not expose the resolved theme name, so the safe visible
        choices are the union reported by installed login themes.

    Raises:
        KeycloakProfileError: If an explicit theme is missing or Keycloak
            reports no locale metadata usable by the picker.
    """

    login_options = tuple(inventory.get("login", ()))
    if selected_theme == DEFAULT_THEME:
        locales = {
            locale
            for option in login_options
            for locale in option.locales
        }
    else:
        selected = next(
            (
                option
                for option in login_options
                if option.name == selected_theme
            ),
            None,
        )
        if selected is None:
            raise KeycloakProfileError(
                f"Selected login theme {selected_theme!r} is not installed."
            )
        locales = set(selected.locales)
    if not locales:
        raise KeycloakProfileError(
            "Keycloak reported no supported locales for the selected login "
            "theme. Verify the theme's message bundles and rerun bootstrap."
        )
    return tuple(sorted(locales, key=str.casefold))


def _prompt_default_locale(
    selected_locales: Sequence[str],
    current: str,
) -> str:
    """Choose one realm default from the selected supported locales.

    Args:
        selected_locales: Locales retained by the multiselect.
        current: Existing realm default locale.

    Returns:
        One selected locale identifier.
    """

    choices = tuple(selected_locales)
    default_index = choices.index(current) + 1 if current in choices else 1
    print("")
    print("Default realm locale")
    for index, locale in enumerate(choices, start=1):
        current_note = " (current)" if locale == current else ""
        print(f"  {index}) {locale}{current_note}")
    while True:
        answer = input(f"Select default locale [{default_index}]: ").strip()
        if not answer:
            return choices[default_index - 1]
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1]
        print(f"Please enter a number from 1 to {len(choices)}.")


def _prompt_localization_settings(
    current: KeycloakLocalizationSettings,
    themes: KeycloakThemeSettings,
    inventory: Mapping[str, Sequence[KeycloakThemeInfo]],
    prompt_boolean: PromptBoolean,
) -> KeycloakLocalizationSettings:
    """Collect localization through the shared installer-style multiselect.

    Args:
        current: Existing realm localization defaults.
        themes: Newly selected realm themes.
        inventory: Authenticated live theme metadata.
        prompt_boolean: Shared Enter-default yes/no prompt.

    Returns:
        Operator-selected localization settings constrained to live login-theme
        locale metadata.
    """

    print("")
    print("Realm localization")
    print("------------------")
    enabled = prompt_boolean(
        "Enable realm internationalization",
        current.enabled,
    )
    if not enabled:
        print("Localization is disabled; configured locale defaults are retained.")
        return replace(current, enabled=False)
    available = _login_theme_locales(inventory, themes.login)
    defaults = tuple(
        locale for locale in current.supported_locales if locale in available
    )
    if not defaults:
        defaults = (current.default_locale,)
        if current.default_locale not in available:
            defaults = (available[0],)
    source = f"login theme {themes.login!r}"
    if themes.login == DEFAULT_THEME:
        source = (
            "the installed login-theme inventory used by the inherited "
            "default"
        )
    selected = select_many(
        "Supported realm locales",
        f"Select locales reported by {source}.",
        tuple(MultiselectOption(locale, locale) for locale in available),
        defaults,
        require_selection=True,
    )
    return KeycloakLocalizationSettings(
        enabled=True,
        supported_locales=selected,
        default_locale=_prompt_default_locale(
            selected,
            current.default_locale,
        ),
    )


def prompt_live_theme_and_localization_settings(
    client: KeycloakAdminClient,
    current_themes: KeycloakThemeSettings,
    current_localization: KeycloakLocalizationSettings,
    prompt_boolean: PromptBoolean,
) -> tuple[KeycloakThemeSettings, KeycloakLocalizationSettings]:
    """Load live theme metadata and collect coherent theme/locale settings.

    Args:
        client: Authenticated Keycloak Admin client.
        current_themes: Existing theme defaults.
        current_localization: Existing localization defaults.
        prompt_boolean: Shared Enter-default yes/no prompt.

    Returns:
        Selected theme and localization settings ready for persistence.
    """

    print("")
    print("Loading installed Keycloak themes and locale support...")
    inventory = load_theme_inventory(client)
    themes = _prompt_theme_settings(inventory, current_themes)
    localization = _prompt_localization_settings(
        current_localization,
        themes,
        inventory,
        prompt_boolean,
    )
    return themes, localization


__all__ = [
    "KeycloakThemeInfo",
    "THEME_TYPES",
    "load_available_themes",
    "load_theme_inventory",
    "prompt_live_theme_and_localization_settings",
    "prompt_live_theme_settings",
]
