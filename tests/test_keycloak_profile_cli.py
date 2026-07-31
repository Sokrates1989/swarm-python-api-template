"""
Module: test_keycloak_profile_cli.py

Description:
    Protects the guided, secret-safe Keycloak bootstrap prompt sequence. The
    complete public target and value review precede the administrator username,
    and the password prompt follows that username without another bootstrap
    summary in between.

Dependencies:
    - Python standard library.
    - scripts/keycloak_profile_bootstrap.py.
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

import keycloak_profile_bootstrap as bootstrap  # noqa: E402
from keycloak_profile_cli import (  # noqa: E402
    prompt_admin_user,
    prompt_bootstrap_values,
    prompt_secret_safe_debug,
)
from keycloak_profile_client import KeycloakProfileError  # noqa: E402


class KeycloakProfileCliTests(unittest.TestCase):
    """Verify the interactive administrator credential prompt boundary."""

    def test_bootstrap_values_are_guided_and_cannot_drift_for_one_run(
        self,
    ) -> None:
        """Accept Enter defaults and reject a bootstrap-only realm override.

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
        )
        with patch("builtins.input", side_effect=[""] * 8), patch(
            "builtins.print"
        ):
            prompt_bootstrap_values(identity)
        with (
            patch("builtins.input", side_effect=["", "another-realm"]),
            patch("builtins.print"),
            self.assertRaisesRegex(KeycloakProfileError, "fixed by"),
        ):
            prompt_bootstrap_values(identity)

    def test_debug_trace_requires_explicit_yes(self) -> None:
        """Keep secret-safe request tracing opt-in.

        Returns:
            Nothing.
        """

        with patch("builtins.input", return_value=""):
            self.assertFalse(prompt_secret_safe_debug())
        with patch("builtins.input", return_value="yes"):
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
                side_effect=lambda *_args: events.append("values"),
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
            patch("builtins.print"),
        ):
            status = bootstrap.main(["--root", str(REPOSITORY_ROOT)])

        self.assertEqual(status, 0)
        self.assertEqual(
            events,
            [
                "target",
                "values",
                "debug",
                "username",
                "password",
                "plan",
                "confirm",
                "apply",
                "completion",
            ],
        )


if __name__ == "__main__":
    unittest.main()
