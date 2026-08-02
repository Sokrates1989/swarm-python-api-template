"""
Module: test_keycloak_profile_access_dialog.py

Description:
    Verifies site-profile role selection, independent predefined-user choices,
    role assignment, temporary-password mode, and the manual-user loop without
    requiring an interactive terminal.

Dependencies:
    - Python standard library.
    - scripts/keycloak_profile_access_dialog.py.
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

from keycloak_profile_access_dialog import (  # noqa: E402
    prompt_application_access,
)
from keycloak_profile_application_access import (  # noqa: E402
    KeycloakBootstrapTestUser,
    KeycloakRealmRole,
)


class KeycloakProfileAccessDialogTests(unittest.TestCase):
    """Protect granular role and bootstrap-user configuration."""

    def setUp(self) -> None:
        """Create reusable profile-defined roles and users.

        Returns:
            Nothing.
        """

        self.roles = (
            KeycloakRealmRole("user", "Standard user"),
            KeycloakRealmRole("admin", "Administrator"),
            KeycloakRealmRole("manager", "Manager"),
        )
        self.users = (
            self._user("test-user", ("user",)),
            self._user("test-manager", ("user", "manager")),
        )
        self.identity = SimpleNamespace(
            realm_roles=self.roles,
            bootstrap_test_users=self.users,
            forbidden_default_usernames=("test",),
        )

    @staticmethod
    def _user(
        username: str,
        roles: tuple[str, ...],
    ) -> KeycloakBootstrapTestUser:
        """Create one secret-free profile-user fixture.

        Args:
            username: Stable fixture username.
            roles: Default application roles.

        Returns:
            Enabled temporary-user declaration selected by default.
        """

        return KeycloakBootstrapTestUser(
            username=username,
            email=f"{username}@example.com",
            first_name="Test",
            last_name="User",
            enabled=True,
            email_verified=True,
            temporary_password=False,
            realm_roles=roles,
            production_cleanup_required=True,
            selected_for_bootstrap=True,
        )

    def test_roles_users_and_manual_loop_are_independently_configurable(
        self,
    ) -> None:
        """Select realm roles, skip one default user, and add one manual user.

        Returns:
            Nothing.
        """

        boolean_answers = iter((True, False, False, True, True, False))

        def prompt_boolean(_label: str, _default: bool) -> bool:
            """Return deterministic yes/no answers for the dialogue.

            Args:
                _label: Ignored prompt label.
                _default: Ignored Enter default.

            Returns:
                Next configured answer.
            """

            return next(boolean_answers)

        with patch(
            "keycloak_profile_access_dialog.select_many",
            side_effect=[
                ("user", "admin"),
                ("user",),
                ("admin",),
            ],
        ), patch(
            "builtins.input",
            side_effect=["manual-admin", "", "", ""],
        ), patch("builtins.print"):
            roles, users = prompt_application_access(
                self.identity,
                prompt_boolean,
            )

        self.assertEqual([role.name for role in roles], ["user", "admin"])
        self.assertTrue(users[0].selected_for_bootstrap)
        self.assertEqual(users[0].realm_roles, ("user",))
        self.assertFalse(users[1].selected_for_bootstrap)
        self.assertEqual(users[2].username, "manual-admin")
        self.assertEqual(users[2].realm_roles, ("admin",))
        self.assertTrue(users[2].temporary_password)
        self.assertTrue(users[2].production_cleanup_required)

    def test_no_selected_realm_roles_disables_every_user(self) -> None:
        """Prevent user creation when no assignable app role was selected.

        Returns:
            Nothing.
        """

        with patch(
            "keycloak_profile_access_dialog.select_many",
            return_value=(),
        ), patch("builtins.print"):
            roles, users = prompt_application_access(
                self.identity,
                lambda _label, default: default,
            )

        self.assertEqual(roles, ())
        self.assertTrue(users)
        self.assertTrue(
            all(not user.selected_for_bootstrap for user in users)
        )

    def test_forbidden_or_duplicate_manual_username_is_reprompted(self) -> None:
        """Reject protected and duplicate names before creating manual intent.

        Returns:
            Nothing.
        """

        boolean_answers = iter((False, False, True, True, False))

        def prompt_boolean(_label: str, _default: bool) -> bool:
            """Return deterministic user-lifecycle answers.

            Args:
                _label: Ignored prompt label.
                _default: Ignored Enter default.

            Returns:
                Next configured answer.
            """

            return next(boolean_answers)

        with patch(
            "keycloak_profile_access_dialog.select_many",
            side_effect=[
                ("user",),
                ("user",),
            ],
        ), patch(
            "builtins.input",
            side_effect=[
                "",
                "Invalid Name",
                "test",
                "test-user",
                "manual-user",
                "",
                "",
                "",
            ],
        ), patch("builtins.print") as printed:
            _, users = prompt_application_access(
                self.identity,
                prompt_boolean,
            )

        self.assertEqual(users[-1].username, "manual-user")
        rendered_messages = " ".join(
            " ".join(str(argument) for argument in call.args)
            for call in printed.call_args_list
        )
        self.assertIn("Username cannot be empty", rendered_messages)
        self.assertIn(
            "Username 'Invalid Name' is invalid",
            rendered_messages,
        )
        self.assertIn(
            "Username 'test' is forbidden by the selected site profile "
            "(auth.forbiddenDefaultUsernames)",
            rendered_messages,
        )
        self.assertIn(
            "Username 'test-user' is already declared by the selected site "
            "profile or this bootstrap run",
            rendered_messages,
        )


if __name__ == "__main__":
    unittest.main()
