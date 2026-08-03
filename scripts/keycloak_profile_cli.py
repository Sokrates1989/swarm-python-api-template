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
from dataclasses import replace

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
from keycloak_profile_realm_configuration import (
    KeycloakEmailSenderSettings,
    KeycloakLocalizationSettings,
)


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
    themes = identity.theme_settings
    print("Realm themes:")
    print(f"  - login: {themes.login}")
    print(f"  - account: {themes.account}")
    print(f"  - admin: {themes.admin}")
    print(f"  - email: {themes.email}")
    localization = identity.localization_settings
    print("Realm localization:")
    print(f"  - enabled: {str(localization.enabled).lower()}")
    print(
        "  - supported locales: "
        + (", ".join(localization.supported_locales) or "none")
    )
    print(f"  - default locale: {localization.default_locale}")
    sender = identity.email_sender_settings
    print("Realm email sender:")
    print(f"  - configured: {str(sender.enabled).lower()}")
    if sender.enabled:
        print(f"  - from: {sender.from_address}")
        print(f"  - host: {sender.host}:{sender.port}")
        print(f"  - STARTTLS: {str(sender.start_tls).lower()}")
        print(f"  - SSL: {str(sender.ssl).lower()}")
        print(f"  - authentication: {str(sender.authentication).lower()}")
        print(f"  - username: {sender.username or 'none'}")
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
    print("it is never printed or persisted in deployment configuration.")
    print("After a new/rotated value is stored, an opt-in private temporary")
    print("editor view is available and deleted immediately after closing.")


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


def _prompt_required_value(label: str, default: str) -> str:
    """Collect a non-empty public value with an optional Enter default.

    Args:
        label: Operator-facing field label.
        default: Existing value selected by Enter when non-empty.

    Returns:
        A non-empty operator selection.
    """

    while True:
        displayed = default or "required"
        answer = input(f"{label} [{displayed}]: ").strip()
        selected = answer or default
        if selected:
            return selected
        print(f"{label} is required; enter a value before continuing.")


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


def _prompt_optional_value(label: str, default: str) -> str:
    """Collect an optional public value with an explicit clearing sentinel.

    Args:
        label: Operator-facing field label.
        default: Existing public value retained when Enter is pressed.

    Returns:
        Selected value, or an empty string when ``none`` is entered.
    """

    displayed = default or "none"
    answer = input(f"{label} [{displayed}]: ").strip()
    if not answer:
        return default
    if answer.lower() in {"none", "clear", "-"}:
        return ""
    return answer


def _prompt_port(label: str, default: int) -> int:
    """Collect a valid TCP port with an Enter default.

    Args:
        label: Operator-facing field label.
        default: Existing port retained when Enter is pressed.

    Returns:
        Integer port from 1 through 65535.
    """

    while True:
        answer = input(f"{label} [{default}]: ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= 65535:
            return int(answer)
        print("Please enter a TCP port from 1 to 65535.")


def _prompt_localization_settings(
    identity: KeycloakIdentity,
) -> KeycloakLocalizationSettings:
    """Collect realm internationalization and locale choices.

    Args:
        identity: Active identity providing localization defaults.

    Returns:
        Operator-selected localization settings.
    """

    current = identity.localization_settings
    print("")
    print("Realm localization")
    print("------------------")
    enabled = _prompt_boolean(
        "Enable realm internationalization", current.enabled
    )
    raw_default = ",".join(current.supported_locales)
    raw_locales = _prompt_value(
        "Supported locales (comma-separated)",
        raw_default,
    )
    locales = tuple(
        dict.fromkeys(
            item.strip() for item in raw_locales.split(",") if item.strip()
        )
    )
    default_locale = _prompt_value(
        "Default locale", current.default_locale
    )
    return KeycloakLocalizationSettings(
        enabled=enabled,
        supported_locales=locales,
        default_locale=default_locale,
    )


def _prompt_email_sender_settings(
    identity: KeycloakIdentity,
    realm_settings: tuple[tuple[str, bool], ...],
) -> KeycloakEmailSenderSettings:
    """Collect public SMTP sender settings while excluding the password.

    Args:
        identity: Active identity providing public SMTP defaults.
        realm_settings: Newly selected realm booleans used to recommend SMTP.

    Returns:
        Operator-selected public email-sender settings. The SMTP password is
        collected only after authentication when the live plan requires it.
    """

    current = identity.email_sender_settings
    selected_realm = dict(realm_settings)
    email_required = (
        selected_realm["verifyEmail"]
        or selected_realm["resetPasswordAllowed"]
    )
    print("")
    print("Realm email sender (SMTP)")
    print("-------------------------")
    print(
        "SMTP is required for verified-email and password-reset messages. "
        "Public sender/server values are saved to .env; the password is "
        "requested later without echo and is never persisted."
    )
    enabled = _prompt_boolean(
        "Configure realm email sender",
        current.enabled or email_required,
    )
    if not enabled:
        if email_required:
            raise KeycloakProfileError(
                "Verified-email or password-reset settings require SMTP. "
                "Rerun and configure the email sender, or disable both "
                "dependent realm settings."
            )
        return replace(current, enabled=False)
    print("Type 'none' to clear an optional sender field.")
    from_address = _prompt_required_value(
        "From email address",
        current.from_address,
    )
    from_display_name = _prompt_optional_value(
        "From display name", current.from_display_name
    )
    reply_to = _prompt_optional_value("Reply-to email", current.reply_to)
    reply_to_display_name = _prompt_optional_value(
        "Reply-to display name", current.reply_to_display_name
    )
    envelope_from = _prompt_optional_value(
        "Envelope-from email", current.envelope_from
    )
    host = _prompt_required_value("SMTP host", current.host)
    port = _prompt_port("SMTP port", current.port)
    start_tls = _prompt_boolean("Use STARTTLS", current.start_tls)
    ssl = _prompt_boolean("Use implicit SSL/TLS", current.ssl)
    authentication = _prompt_boolean(
        "SMTP server requires authentication", current.authentication
    )
    username = ""
    if authentication:
        username = _prompt_required_value("SMTP username", current.username)
    return KeycloakEmailSenderSettings(
        enabled=True,
        from_address=from_address,
        from_display_name=from_display_name,
        reply_to=reply_to,
        reply_to_display_name=reply_to_display_name,
        envelope_from=envelope_from,
        host=host,
        port=port,
        start_tls=start_tls,
        ssl=ssl,
        authentication=authentication,
        username=username,
    )


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
    print("")
    print("Installed realm themes are selected after Keycloak admin login.")
    localization_settings = _prompt_localization_settings(identity)
    email_sender_settings = _prompt_email_sender_settings(
        identity,
        realm_settings,
    )
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
        theme_settings=identity.theme_settings,
        localization_settings=localization_settings,
        email_sender_settings=email_sender_settings,
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


def prompt_smtp_password(
    identity: KeycloakIdentity,
    plan: Mapping[str, object],
) -> str | None:
    """Collect a runtime SMTP password only when the live plan needs a write.

    Args:
        identity: Active profile-derived Keycloak identity.
        plan: Sanitized live-state plan containing the password requirement.

    Returns:
        Confirmed runtime password, or ``None`` when no SMTP write needs it.

    Raises:
        KeycloakProfileError: If the password is empty or confirmation differs.
    """

    if plan.get("smtpPasswordRequired") is not True:
        return None
    sender = identity.email_sender_settings
    print("")
    print("Realm SMTP credential")
    print("---------------------")
    print(f"Server: {sender.host}:{sender.port}")
    print(f"Username: {sender.username}")
    print("The password is sent only to Keycloak for realm update and testing.")
    print("It is never written to JSON, .env, logs, plans, or summaries.")
    password = getpass.getpass("SMTP password: ")
    confirmation = getpass.getpass("Confirm SMTP password: ")
    if not password:
        raise KeycloakProfileError("SMTP password is required for this plan.")
    if password != confirmation:
        raise KeycloakProfileError("SMTP password confirmation differs.")
    return password


def prompt_secret_safe_debug() -> bool:
    """Explain and ask whether safe Admin API tracing should be enabled.

    Returns:
        True only for an explicit ``y`` or ``yes`` answer. Request bodies,
        headers, query values, and credentials remain excluded from tracing.
    """

    print(
        "Tracing shows Keycloak Admin API methods, paths, query-key names, "
        "and status codes."
    )
    print(
        "It never shows request bodies, headers, query values, tokens, "
        "passwords, or client secrets."
    )
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
        ("Realm themes", "realmThemes"),
        ("Realm localization", "realmLocalization"),
        ("Realm email sender", "realmEmailSender"),
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
    if plan.get("smtpPasswordRequired") is True:
        print("  SMTP password           required after plan approval")
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


def authenticate_admin(
    identity: KeycloakIdentity,
    admin_user: str,
    *,
    debug: bool = False,
) -> KeycloakAdminClient:
    """Authenticate once while preserving the adjacent credential prompts.

    Args:
        identity: Profile-derived Keycloak identity.
        admin_user: Existing Keycloak administrator username.
        debug: Emit secret-safe Admin API request traces when true.

    Returns:
        Authenticated Keycloak Admin client.

    Raises:
        KeycloakProfileError: If password input or authentication fails.
    """

    password = getpass.getpass(
        f"Keycloak admin password for {admin_user}: "
    )
    if not password:
        raise KeycloakProfileError("Keycloak admin password is required.")
    print("\nAuthenticating with the existing Keycloak server...")
    try:
        return KeycloakAdminClient(
            identity,
            admin_user,
            password,
            debug=debug,
        )
    finally:
        password = ""


def inspect_reconciliation_plan(
    client: KeycloakAdminClient,
    *,
    replace_secret: bool,
) -> tuple[bool, dict[str, object]]:
    """Inspect Docker and Keycloak state after authenticated configuration.

    Args:
        client: Authenticated client carrying the final selected identity.
        replace_secret: Whether the requested plan includes rotation.

    Returns:
        Docker-secret presence and sanitized reconciliation plan.

    Raises:
        KeycloakProfileError: If live Keycloak inspection fails.
        KeycloakSecretBridgeError: If Docker secret state cannot be inspected.
    """

    identity = client.identity
    print("\nInspecting the existing Keycloak server and Docker secret state...")
    docker_present = docker_secret_exists(identity.docker_secret)
    plan = build_reconciliation_plan(
        client,
        docker_secret_present=docker_present,
        replace_secret=replace_secret,
    )
    return docker_present, plan


def authenticate_and_plan(
    identity: KeycloakIdentity,
    admin_user: str,
    *,
    replace_secret: bool,
    debug: bool = False,
) -> tuple[KeycloakAdminClient, bool, dict[str, object]]:
    """Authenticate and inspect directly for backward-compatible callers.

    Interactive bootstrap uses the split functions so live theme selection can
    occur after authentication but before plan construction.

    Args:
        identity: Profile-derived Keycloak identity.
        admin_user: Existing Keycloak administrator username.
        replace_secret: Whether the requested plan includes rotation.
        debug: Emit secret-safe Admin API request traces when true.

    Returns:
        Authenticated client, Docker-secret presence, and sanitized plan.
    """

    client = authenticate_admin(identity, admin_user, debug=debug)
    docker_present, plan = inspect_reconciliation_plan(
        client,
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


def prompt_admin_ui_verification(
    identity: KeycloakIdentity,
    summary: Mapping[str, object],
    *,
    wait_for_operator: bool,
) -> None:
    """Print and optionally pause for the required Admin UI review.

    Args:
        identity: Reconciled profile-derived Keycloak identity.
        summary: Secret-free reconciliation summary including SMTP test state.
        wait_for_operator: Pause until Enter when running interactively.

    Returns:
        Nothing. This checklist supplements automated API verification and
        external email-delivery testing remains an operator responsibility.
    """

    console = (
        f"{identity.server_url}/admin/master/console/#/"
        f"{identity.realm}/realm-settings"
    )
    print("")
    print("⚠️  Please verify your realm settings in Keycloak Admin UI.")
    print("----------------------------------------------------------")
    print(f"Open: {console}")
    print("1. Themes: verify login, account, admin, and email themes.")
    print(
        "2. Localization: verify internationalization, supported locales, "
        "and the default locale."
    )
    sender = identity.email_sender_settings
    if sender.enabled:
        print(
            "3. Email: verify sender, SMTP host/port, encryption, and "
            "authentication; then click 'Test connection'."
        )
        if summary.get("smtpConnectionTest") == "manual-ui-required":
            print(
                "   Automated SMTP testing was skipped because the existing "
                "write-only password was not re-entered."
            )
        print(
            "4. Trigger one real verification or password-reset email and "
            "confirm delivery."
        )
    else:
        print(
            "3. Email: this profile did not manage a sender. Verify any "
            "existing realm SMTP state, or keep verification/reset email "
            "features disabled."
        )
    if wait_for_operator:
        input("Press Enter after completing the Admin UI verification: ")


__all__ = [
    "authenticate_admin",
    "authenticate_and_plan",
    "confirm_apply",
    "print_completion",
    "prompt_admin_ui_verification",
    "print_plan",
    "print_target",
    "prompt_admin_user",
    "prompt_bootstrap_values",
    "prompt_bootstrap_test_user_passwords",
    "prompt_smtp_password",
    "prompt_secret_safe_debug",
    "inspect_reconciliation_plan",
]
