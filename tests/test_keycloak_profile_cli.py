"""
Module: test_keycloak_profile_cli.py

Description:
    Protects the guided, secret-safe Keycloak bootstrap prompt sequence. The
    complete public target and value review precede the administrator username,
    and the password prompt follows that username without another bootstrap
    summary in between.

Dependencies:
    - Python standard library.
    - scripts/keycloak_profile_bootstrap_cli.py.
    - scripts/keycloak_profile_cli.py.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

import keycloak_profile_bootstrap_cli as bootstrap  # noqa: E402
from keycloak_profile_cli import (  # noqa: E402
    _prompt_required_value,
    prompt_admin_ui_verification,
    prompt_admin_user,
    prompt_bootstrap_values,
    prompt_bootstrap_test_user_passwords,
    prompt_secret_safe_debug,
    prompt_smtp_password,
)
from keycloak_profile_client import KeycloakProfileError  # noqa: E402
from keycloak_profile_realm_configuration import (  # noqa: E402
    KeycloakEmailSenderSettings,
    KeycloakLocalizationSettings,
    KeycloakThemeSettings,
)


class KeycloakProfileCliTests(unittest.TestCase):
    """Verify the interactive administrator credential prompt boundary."""

    def test_required_smtp_value_reprompts_without_an_empty_default(
        self,
    ) -> None:
        """Keep a guided SMTP field local until it has a usable value.

        Returns:
            Nothing.
        """

        with patch(
            "builtins.input",
            side_effect=["", "smtp.example.com"],
        ), patch("builtins.print") as printed:
            selected = _prompt_required_value("SMTP host", "")

        self.assertEqual(selected, "smtp.example.com")
        self.assertIn("is required", str(printed.call_args_list))

    def test_bootstrap_values_accept_defaults_and_operator_changes(
        self,
    ) -> None:
        """Return Enter defaults and actual operator-entered identity values.

        Returns:
            Nothing.
        """

        identity = SimpleNamespace(
            server_url="https://keycloak.example.com",
            realm="example",
            realm_display_name="Example",
            frontend_client_id="example-frontend",
            backend_client_id="example-backend",
            frontend_root_url="https://app.example.com",
            api_root_url="https://api.example.com",
            audience="example-backend",
            realm_settings=(
                ("enabled", True),
                ("registrationAllowed", False),
                ("resetPasswordAllowed", True),
                ("rememberMe", True),
                ("verifyEmail", True),
                ("loginWithEmailAllowed", True),
            ),
            theme_settings=KeycloakThemeSettings(
                "default", "default", "default", "default"
            ),
            localization_settings=KeycloakLocalizationSettings(
                True, ("de", "en"), "de"
            ),
            email_sender_settings=KeycloakEmailSenderSettings(
                True,
                "noreply@example.com",
                "Example",
                "",
                "",
                "",
                "smtp.example.com",
                587,
                True,
                False,
                True,
                "noreply@example.com",
            ),
            bootstrap_test_users_enabled=False,
            bootstrap_test_users=(),
        )
        with patch("builtins.input", side_effect=[""] * 32), patch(
            "builtins.print"
        ):
            defaults = prompt_bootstrap_values(identity)
        self.assertEqual(defaults.frontend_client_id, "example-frontend")
        with patch(
            "builtins.input",
            side_effect=[
                "another-realm",
                "Another Realm",
                "selected-frontend",
                "selected-backend",
                "https://selected.example.com",
                "https://api-selected.example.com",
                "selected-audience",
                *([""] * 25),
            ],
        ), patch("builtins.print"):
            selected = prompt_bootstrap_values(identity)
        self.assertEqual(selected.realm, "another-realm")
        self.assertEqual(selected.realm_display_name, "Another Realm")
        self.assertEqual(selected.frontend_client_id, "selected-frontend")
        self.assertEqual(selected.backend_client_id, "selected-backend")
        self.assertEqual(selected.audience, "selected-audience")
        self.assertEqual(selected.server_url, identity.server_url)

    def test_missing_test_user_password_is_confirmed_without_echo(self) -> None:
        """Collect only planned creation credentials and reject a mismatch.

        Returns:
            Nothing.
        """

        plan = {
            "bootstrapTestUserActions": {
                "test-user": "create",
                "test-admin": "keep",
                "test-manager": "set-password",
            }
        }
        with patch(
            "keycloak_profile_cli.getpass.getpass",
            side_effect=[
                "admin-secret",
                "admin-secret",
                "runtime-secret",
                "runtime-secret",
            ],
        ):
            passwords = prompt_bootstrap_test_user_passwords(
                SimpleNamespace(),
                plan,
            )
        self.assertEqual(
            passwords,
            {
                "test-manager": "admin-secret",
                "test-user": "runtime-secret",
            },
        )

        with patch(
            "keycloak_profile_cli.getpass.getpass",
            side_effect=["one", "different"],
        ), self.assertRaisesRegex(KeycloakProfileError, "differs"):
            prompt_bootstrap_test_user_passwords(SimpleNamespace(), plan)

    def test_smtp_password_is_hidden_and_confirmed_only_when_required(
        self,
    ) -> None:
        """Collect SMTP credentials only for a plan that mutates the sender.

        Returns:
            Nothing.
        """

        identity = SimpleNamespace(
            email_sender_settings=SimpleNamespace(
                host="smtp.example.com",
                port=587,
                username="smtp-user",
            )
        )
        with patch(
            "keycloak_profile_cli.getpass.getpass",
            side_effect=["smtp-secret", "smtp-secret"],
        ):
            password = prompt_smtp_password(
                identity,
                {"smtpPasswordRequired": True},
            )
        self.assertEqual(password, "smtp-secret")
        self.assertIsNone(
            prompt_smtp_password(identity, {"smtpPasswordRequired": False})
        )

    def test_admin_ui_checklist_includes_email_delivery_verification(
        self,
    ) -> None:
        """Direct the operator to realm settings and a real email check.

        Returns:
            Nothing.
        """

        identity = SimpleNamespace(
            server_url="https://keycloak.example.com",
            realm="example",
            email_sender_settings=SimpleNamespace(enabled=True),
        )
        with patch("builtins.print") as printed:
            prompt_admin_ui_verification(
                identity,
                {"smtpConnectionTest": "passed"},
                wait_for_operator=False,
            )
        rendered = "\n".join(
            str(call.args[0]) for call in printed.call_args_list if call.args
        )
        self.assertIn("#/example/realm-settings", rendered)
        self.assertIn("Test connection", rendered)
        self.assertIn("real verification or password-reset email", rendered)

    def test_password_prompt_repeats_selected_roles_and_mode(self) -> None:
        """Show exact user intent before collecting a hidden credential.

        Returns:
            Nothing.
        """

        identity = SimpleNamespace(
            bootstrap_test_users=(
                SimpleNamespace(
                    username="manual-admin",
                    realm_roles=("user", "admin"),
                    temporary_password=True,
                ),
            )
        )
        plan = {
            "bootstrapTestUserActions": {"manual-admin": "create"}
        }
        with patch(
            "keycloak_profile_cli.getpass.getpass",
            side_effect=["runtime-secret", "runtime-secret"],
        ), patch("builtins.print") as printed:
            passwords = prompt_bootstrap_test_user_passwords(identity, plan)

        rendered = "\n".join(
            str(call.args[0]) for call in printed.call_args_list if call.args
        )
        self.assertEqual(passwords, {"manual-admin": "runtime-secret"})
        self.assertIn("Roles: user, admin", rendered)
        self.assertIn("temporary; change required", rendered)

    def test_changed_backend_client_becomes_matching_audience_default(
        self,
    ) -> None:
        """Derive the audience default from a newly entered backend client ID.

        Returns:
            Nothing.
        """

        identity = SimpleNamespace(
            server_url="https://keycloak.example.com",
            realm="example",
            realm_display_name="Example",
            frontend_client_id="example-frontend",
            backend_client_id="example-backend",
            frontend_root_url="https://app.example.com",
            api_root_url="https://api.example.com",
            audience="example-backend",
            realm_settings=(
                ("enabled", True),
                ("registrationAllowed", False),
                ("resetPasswordAllowed", True),
                ("rememberMe", True),
                ("verifyEmail", True),
                ("loginWithEmailAllowed", True),
            ),
            theme_settings=KeycloakThemeSettings(
                "default", "default", "default", "default"
            ),
            localization_settings=KeycloakLocalizationSettings(
                True, ("de", "en"), "de"
            ),
            email_sender_settings=KeycloakEmailSenderSettings(
                True,
                "noreply@example.com",
                "Example",
                "",
                "",
                "",
                "smtp.example.com",
                587,
                True,
                False,
                True,
                "noreply@example.com",
            ),
            bootstrap_test_users_enabled=False,
            bootstrap_test_users=(),
        )
        answers = ["", "", "", "selected-backend", "", "", ""] + [
            ""
        ] * 25
        with patch("builtins.input", side_effect=answers), patch(
            "builtins.print"
        ):
            selected = prompt_bootstrap_values(identity)

        self.assertEqual(selected.backend_client_id, "selected-backend")
        self.assertEqual(selected.audience, "selected-backend")

    def test_debug_trace_explains_safety_and_requires_explicit_yes(
        self,
    ) -> None:
        """Explain trace boundaries while keeping request tracing opt-in.

        Returns:
            Nothing.
        """

        with patch("builtins.input", return_value=""), patch(
            "builtins.print"
        ) as print_mock:
            self.assertFalse(prompt_secret_safe_debug())

        rendered_explanation = " ".join(
            " ".join(str(argument) for argument in call.args)
            for call in print_mock.call_args_list
        )
        self.assertIn("Admin API methods", rendered_explanation)
        self.assertIn("status codes", rendered_explanation)
        self.assertIn("never shows request bodies", rendered_explanation)
        self.assertIn("client secrets", rendered_explanation)

        with patch("builtins.input", return_value="yes"), patch(
            "builtins.print"
        ):
            self.assertTrue(prompt_secret_safe_debug())

    def test_admin_username_uses_explicit_or_enter_default(self) -> None:
        """Return an entered username and map an empty answer to ``admin``.

        Returns:
            Nothing.
        """

        with patch("builtins.input", return_value="Patrick"):
            self.assertEqual(prompt_admin_user(), "Patrick")
        with patch("builtins.input", return_value=""):
            self.assertEqual(prompt_admin_user(), "admin")

    def test_target_precedes_adjacent_username_and_password_prompts(self) -> None:
        """Keep bootstrap output outside the username/password prompt pair.

        Returns:
            Nothing.
        """

        events: list[str] = []
        profile = object()
        identity = object()
        client = object()
        plan: dict[str, object] = {"blockers": []}
        selected_values = SimpleNamespace(
            apply_access_selection=lambda active_identity: active_identity
        )

        with (
            patch.object(
                bootstrap,
                "load_executable_profile",
                side_effect=lambda _root: profile,
            ),
            patch.object(
                bootstrap,
                "load_keycloak_identity",
                side_effect=lambda _profile: identity,
            ),
            patch.object(
                bootstrap,
                "print_target",
                side_effect=lambda *_args: events.append("target"),
            ),
            patch.object(
                bootstrap,
                "prompt_bootstrap_values",
                side_effect=lambda *_args: (
                    events.append("values") or selected_values
                ),
            ),
            patch.object(
                bootstrap,
                "persist_keycloak_values",
                side_effect=lambda active, _values: (
                    events.append("persist") or active,
                    False,
                ),
            ),
            patch.object(
                bootstrap,
                "prompt_secret_safe_debug",
                side_effect=lambda: events.append("debug") or True,
            ),
            patch.object(
                bootstrap,
                "prompt_admin_user",
                side_effect=lambda: events.append("username") or "Patrick",
            ),
            patch.object(
                bootstrap,
                "authenticate_and_plan",
                side_effect=lambda *_args, **_kwargs: (
                    events.append("password") or client,
                    False,
                    plan,
                ),
            ),
            patch.object(
                bootstrap,
                "print_plan",
                side_effect=lambda *_args: events.append("plan"),
            ),
            patch.object(
                bootstrap,
                "prompt_smtp_password",
                side_effect=lambda *_args: events.append("smtp-password") or None,
            ),
            patch.object(
                bootstrap,
                "prompt_bootstrap_test_user_passwords",
                side_effect=lambda *_args: events.append("user-passwords") or {},
            ),
            patch.object(
                bootstrap,
                "confirm_apply",
                side_effect=lambda *_args: events.append("confirm") or True,
            ),
            patch.object(
                bootstrap,
                "reconcile_authenticated",
                side_effect=lambda *_args, **_kwargs: (
                    events.append("apply") or {}
                ),
            ),
            patch.object(
                bootstrap,
                "print_completion",
                side_effect=lambda *_args: events.append("completion"),
            ),
            patch.object(
                bootstrap,
                "prompt_admin_ui_verification",
                side_effect=lambda *_args, **_kwargs: events.append(
                    "admin-ui-verification"
                ),
            ),
            patch("builtins.print"),
        ):
            status = bootstrap.main(["--root", str(REPOSITORY_ROOT)])

        self.assertEqual(status, 0)
        self.assertEqual(
            events,
            [
                "target",
                "values",
                "persist",
                "target",
                "debug",
                "username",
                "password",
                "plan",
                "smtp-password",
                "user-passwords",
                "confirm",
                "apply",
                "completion",
                "admin-ui-verification",
            ],
        )


if __name__ == "__main__":
    unittest.main()
