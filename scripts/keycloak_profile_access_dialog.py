"""
Module: keycloak_profile_access_dialog.py

Description:
    Collects runtime Keycloak application-role and bootstrap-user intent from
    the generic site-profile dialogue. Profile declarations supply allowed
    defaults, while installer-style checkbox selectors let operators choose
    exact realm roles and per-user assignments. Passwords are deliberately
    excluded and remain in the post-authentication credential boundary.

Dependencies:
    - Python standard library.
    - Executable-profile validation constants.
    - Keycloak application-access models.
    - scripts/terminal_multiselect.py.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from executable_profile_keycloak_validation import is_backend_compatible_email
from executable_profile_support import NAME_PATTERN
from keycloak_profile_application_access import (
    KeycloakBootstrapTestUser,
    KeycloakRealmRole,
)
from keycloak_profile_client import KeycloakIdentity
from terminal_multiselect import MultiselectOption, select_many


PromptBoolean = Callable[[str, bool], bool]


def _prompt_validated_value(
    label: str,
    default: str,
    validator: Callable[[str], bool],
    error_message: str,
) -> str:
    """Read one non-secret public value until it passes validation.

    Args:
        label: Operator-facing field label.
        default: Value selected when Enter is pressed; an empty default makes
            explicit input mandatory.
        validator: Predicate accepting safe candidate values.
        error_message: Guidance printed after invalid input.

    Returns:
        Validated, trimmed public value.
    """

    while True:
        suffix = f" [{default}]" if default else ""
        answer = input(f"{label}{suffix}: ").strip() or default
        if validator(answer):
            return answer
        print(error_message)


def _role_options(
    roles: Sequence[KeycloakRealmRole],
) -> tuple[MultiselectOption, ...]:
    """Convert realm-role models to terminal checkbox options.

    Args:
        roles: Profile-declared application roles.

    Returns:
        Stable options preserving profile order and descriptions.
    """

    return tuple(
        MultiselectOption(role.name, role.name, role.description)
        for role in roles
    )


def _prompt_realm_roles(
    identity: KeycloakIdentity,
) -> tuple[KeycloakRealmRole, ...]:
    """Choose which profile roles this bootstrap should create and manage.

    Args:
        identity: Active identity containing allowed profile role definitions.

    Returns:
        Selected role definitions in profile order.
    """

    roles = tuple(getattr(identity, "realm_roles", ()))
    if not roles:
        print("\nNo application realm roles are declared by this profile.")
        return ()
    selected = set(
        select_many(
            "Application realm roles",
            "Select roles to create/manage and make assignable to users.",
            _role_options(roles),
            tuple(role.name for role in roles),
        )
    )
    return tuple(role for role in roles if role.name in selected)


def _prompt_user_roles(
    username: str,
    roles: Sequence[KeycloakRealmRole],
    defaults: Sequence[str],
) -> tuple[str, ...]:
    """Choose at least one selected application role for one user.

    Args:
        username: User receiving the role assignments.
        roles: Realm roles selected earlier in the dialogue.
        defaults: Profile-declared assignments to preselect when still valid.

    Returns:
        Selected role names in realm-role order.
    """

    allowed = {role.name for role in roles}
    active_defaults = tuple(role for role in defaults if role in allowed)
    if not active_defaults:
        active_defaults = (roles[0].name,)
    return select_many(
        f"Roles for {username}",
        "Select the application roles assigned to this bootstrap user.",
        _role_options(roles),
        active_defaults,
        require_selection=True,
    )


def _configure_declared_users(
    identity: KeycloakIdentity,
    roles: Sequence[KeycloakRealmRole],
    prompt_boolean: PromptBoolean,
) -> tuple[KeycloakBootstrapTestUser, ...]:
    """Collect independent lifecycle and roles for profile-declared users.

    Args:
        identity: Active identity with secret-free user defaults.
        roles: Realm roles selected for this bootstrap.
        prompt_boolean: Shared yes/no prompt preserving Enter defaults.

    Returns:
        Every profile declaration with its per-run selected state.
    """

    configured: list[KeycloakBootstrapTestUser] = []
    for user in getattr(identity, "bootstrap_test_users", ()):
        print("")
        selected = prompt_boolean(
            f"Create/update profile user {user.username!r}",
            user.selected_for_bootstrap,
        )
        if not selected:
            configured.append(replace(user, selected_for_bootstrap=False))
            continue
        assignments = _prompt_user_roles(user.username, roles, user.realm_roles)
        temporary = prompt_boolean(
            f"Require {user.username!r} to change password at first login",
            user.temporary_password,
        )
        configured.append(
            replace(
                user,
                realm_roles=assignments,
                temporary_password=temporary,
                selected_for_bootstrap=True,
            )
        )
    return tuple(configured)


def _prompt_manual_username(
    existing_usernames: set[str],
    forbidden_usernames: set[str],
) -> str:
    """Read a unique username and explain its exact rejection reason.

    Args:
        existing_usernames: Profile-declared and previously entered usernames
            that cannot be declared again in the current bootstrap.
        forbidden_usernames: Site-profile policy names unavailable for new
            automated bootstrap declarations. Existing realm accounts are
            outside this input validation boundary.

    Returns:
        A trimmed username accepted by syntax, uniqueness, and profile policy.
    """

    while True:
        username = input("Username: ").strip()
        if not username:
            print("Username cannot be empty.")
            continue
        if not NAME_PATTERN.fullmatch(username):
            print(
                f"Username {username!r} is invalid. Use 1-128 lowercase "
                "letters, digits, dots, underscores, or hyphens, starting "
                "with a letter or digit."
            )
            continue
        if username in forbidden_usernames:
            print(
                f"Username {username!r} is reserved from automated bootstrap "
                "creation by the selected site profile "
                "(auth.forbiddenDefaultUsernames). This does not classify or "
                "delete an existing Keycloak account; choose another new "
                "bootstrap username."
            )
            continue
        if username in existing_usernames:
            print(
                f"Username {username!r} is already declared by the selected "
                "site profile or this bootstrap run. Choose another username."
            )
            continue
        return username


def _manual_user_identity(
    existing_usernames: set[str],
    existing_emails: set[str],
    forbidden_usernames: set[str],
) -> tuple[str, str, str, str]:
    """Collect safe, unique public identity fields for one manual user.

    Args:
        existing_usernames: Profile and previously entered usernames.
        existing_emails: Profile and previously entered email addresses.
        forbidden_usernames: Profile-protected usernames unavailable here.

    Returns:
        Username, email, first name, and last name.
    """

    username = _prompt_manual_username(
        existing_usernames,
        forbidden_usernames,
    )
    email = _prompt_validated_value(
        "Email",
        f"{username}@example.com",
        lambda value: is_backend_compatible_email(value)
        and value not in existing_emails,
        "Enter a unique email accepted by the backend; .invalid, .test, "
        ".local, and .localhost addresses are not supported.",
    )
    first_name = _prompt_validated_value(
        "First name",
        username,
        bool,
        "First name cannot be empty.",
    )
    last_name = _prompt_validated_value(
        "Last name",
        "User",
        bool,
        "Last name cannot be empty.",
    )
    return username, email, first_name, last_name


def _prompt_manual_user(
    roles: Sequence[KeycloakRealmRole],
    existing_usernames: set[str],
    existing_emails: set[str],
    forbidden_usernames: set[str],
    prompt_boolean: PromptBoolean,
) -> KeycloakBootstrapTestUser:
    """Collect one additional secret-free runtime bootstrap user.

    Args:
        roles: Realm roles available for assignment.
        existing_usernames: Usernames unavailable for reuse.
        existing_emails: Email addresses unavailable for reuse.
        forbidden_usernames: Profile-protected usernames.
        prompt_boolean: Shared yes/no prompt preserving Enter defaults.

    Returns:
        Selected temporary user definition without a password.
    """

    username, email, first_name, last_name = _manual_user_identity(
        existing_usernames,
        existing_emails,
        forbidden_usernames,
    )
    default_role = next(
        (role.name for role in roles if role.name == "user"),
        roles[0].name,
    )
    assignments = _prompt_user_roles(username, roles, (default_role,))
    temporary = prompt_boolean(
        f"Require {username!r} to change password at first login",
        True,
    )
    return KeycloakBootstrapTestUser(
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name,
        enabled=True,
        email_verified=True,
        temporary_password=temporary,
        realm_roles=assignments,
        production_cleanup_required=True,
        selected_for_bootstrap=True,
    )


def _prompt_manual_users(
    identity: KeycloakIdentity,
    roles: Sequence[KeycloakRealmRole],
    declared: Sequence[KeycloakBootstrapTestUser],
    prompt_boolean: PromptBoolean,
) -> tuple[KeycloakBootstrapTestUser, ...]:
    """Loop until no further manual bootstrap users are requested.

    Args:
        identity: Active identity supplying forbidden usernames.
        roles: Realm roles available for assignment.
        declared: Already configured profile users.
        prompt_boolean: Shared yes/no prompt preserving Enter defaults.

    Returns:
        Additional runtime-only user definitions.
    """

    usernames = {user.username for user in declared}
    emails = {user.email for user in declared}
    forbidden = set(identity.forbidden_default_usernames)
    additional: list[KeycloakBootstrapTestUser] = []
    while True:
        label = (
            "Add another manual bootstrap user"
            if additional
            else "Add a manual bootstrap user"
        )
        if not prompt_boolean(label, False):
            break
        print(
            "Manual bootstrap users are enabled, email-verified, and marked "
            "for production cleanup."
        )
        user = _prompt_manual_user(
            roles,
            usernames,
            emails,
            forbidden,
            prompt_boolean,
        )
        additional.append(user)
        usernames.add(user.username)
        emails.add(user.email)
    return tuple(additional)


def prompt_application_access(
    identity: KeycloakIdentity,
    prompt_boolean: PromptBoolean,
) -> tuple[
    tuple[KeycloakRealmRole, ...],
    tuple[KeycloakBootstrapTestUser, ...],
]:
    """Collect roles, individual declared users, and additional users.

    Args:
        identity: Active profile/deployment Keycloak identity.
        prompt_boolean: Shared yes/no prompt preserving Enter defaults.

    Returns:
        Selected role declarations and complete per-run user intent.
    """

    print("")
    print("Application roles and bootstrap users")
    print("-------------------------------------")
    print("Role options and predefined users come from the selected site profile.")
    print("Deselected roles are not deleted; skipped users are left unchanged.")
    roles = _prompt_realm_roles(identity)
    if not roles:
        skipped = tuple(
            replace(user, selected_for_bootstrap=False)
            for user in getattr(identity, "bootstrap_test_users", ())
        )
        print("No roles selected; bootstrap user creation is disabled.")
        return (), skipped
    declared = _configure_declared_users(identity, roles, prompt_boolean)
    manual = _prompt_manual_users(
        identity,
        roles,
        declared,
        prompt_boolean,
    )
    users = (*declared, *manual)
    if any(user.selected_for_bootstrap for user in users):
        print("[WARN] Once you enter production mode, delete bootstrap users.")
        print("Passwords are requested later only when live state requires one.")
    return roles, users


__all__ = ["prompt_application_access"]
