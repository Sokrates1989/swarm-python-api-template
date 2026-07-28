"""
Module: test_profile_secret_routing.py

Description:
    Verifies that secret-menu visibility, exact-name routing, and batch template
    selection come from site-config data rather than renderer or database type.

Dependencies:
    - Python standard library.
    - Bash and jq for focused runtime routing checks.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SECRET_MENU = (
    REPOSITORY_ROOT / "setup" / "modules" / "docker-secrets-menu.sh"
)
SECRET_MANAGER = (
    REPOSITORY_ROOT / "setup" / "modules" / "secret-manager.sh"
)
SITE_HELPERS = (
    REPOSITORY_ROOT / "setup" / "modules" / "site_helpers.sh"
)
MENU_HANDLERS = (
    REPOSITORY_ROOT / "setup" / "modules" / "menu_handlers.sh"
)
KEYCLOAK_BOOTSTRAP = (
    REPOSITORY_ROOT / "setup" / "modules" / "keycloak-bootstrap.sh"
)
NATIVE_BASH_AND_JQ = (
    not sys.platform.startswith("win")
    and shutil.which("bash") is not None
    and shutil.which("jq") is not None
)


class ProfileSecretRoutingStaticTests(unittest.TestCase):
    """Protect the site-config-only secret-routing boundary on every host."""

    def test_secure_messaging_declares_literal_names_and_template(self) -> None:
        """Keep the internal profile self-contained in site-config data.

        Returns:
            Nothing.
        """

        profile = json.loads(
            (
                REPOSITORY_ROOT
                / "site-configs"
                / "secure_messaging.json"
            ).read_text(encoding="utf-8")
        )

        self.assertIs(profile["secretsConfig"]["prefixed"], False)
        self.assertEqual(
            profile["secretsConfig"]["template"],
            "setup/templates/secrets.secure-messaging.env.template",
        )
        self.assertGreater(len(profile["secrets"]), 0)

    def test_secret_menus_do_not_route_by_renderer_or_database(self) -> None:
        """Reject the former schema and DB-type shortcuts.

        Returns:
            Nothing.
        """

        secret_source = SECRET_MENU.read_text(encoding="utf-8")
        menu_source = MENU_HANDLERS.read_text(encoding="utf-8")
        requires = menu_source[
            menu_source.index("_profile_requires_secrets()")
            : menu_source.index("_primary_service_suffix()")
        ]

        self.assertIn("_profile_secrets_use_exact_names", secret_source)
        self.assertIn("profile_supports_secret_file_workflow", menu_source)
        self.assertNotIn(
            "profile_uses_executable_renderer",
            secret_source[
                secret_source.index("manage_docker_secrets_menu()") :
            ],
        )
        self.assertIn("site_profile_declares_secrets", requires)
        self.assertNotIn("profile_uses_executable_renderer", requires)


@unittest.skipUnless(
    NATIVE_BASH_AND_JQ,
    "Secret-routing integration requires native Bash and jq.",
)
class ProfileSecretRoutingLinuxTests(unittest.TestCase):
    """Exercise exact secret template routing with the real Bash module."""

    def test_secure_messaging_uses_unprefixed_profile_template(self) -> None:
        """Pass literal names and the declared template to the shared importer.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(SECRET_MENU)}
create_secrets_from_env_file() {{
    printf 'FILE=%s\\nTEMPLATE=%s\\nPREFIX=%s\\nALLOWED=%s\\nENFORCE=%s\\n' \
        "$1" "$2" "$3" "$4" "$5"
}}
PROJECT_ROOT={bash_quote(REPOSITORY_ROOT)}
DEPLOYMENT_PROFILE_ID=secure_messaging
STACK_NAME=secure_messaging
create_profile_secrets_from_env_file /tmp/saved-secrets.env
"""
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("FILE=/tmp/saved-secrets.env", completed.stdout)
        self.assertIn(
            "TEMPLATE="
            f"{REPOSITORY_ROOT}/setup/templates/"
            "secrets.secure-messaging.env.template",
            completed.stdout,
        )
        self.assertIn("PREFIX=\n", completed.stdout)
        self.assertIn(
            "ALLOWED=secure_messaging_auth_token",
            completed.stdout,
        )
        self.assertIn(
            "secure_messaging_email_passwords",
            completed.stdout,
        )
        self.assertIn("ENFORCE=true", completed.stdout)

    def test_exact_batch_import_rejects_undeclared_keys(self) -> None:
        """Reject extra exact Docker secret names before any mutation.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary:
            values_file = Path(temporary) / "secrets.env"
            values_file.write_text(
                "declared=value\nundeclared=value\n",
                encoding="utf-8",
            )
            script = f"""
source {bash_quote(SECRET_MANAGER)}
! _validate_secret_env_keys \
    {bash_quote(values_file)} \
    $'declared\\nsecond_declared' \
    true
"""
            completed = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Undeclared Docker secret key", completed.stderr)

    def test_empty_exact_allowlist_rejects_keycloak_only_profile_values(
        self,
    ) -> None:
        """Reject every batch value when only a Keycloak credential exists.

        Exact-name profiles exclude Keycloak client credentials from batch
        import because reconciliation owns their lifecycle. When that leaves
        an empty allowlist, validation must remain enforced instead of falling
        back to unrestricted legacy behavior.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            values_file = write_keycloak_only_profile_fixture(project_root)

            script = f"""
source {bash_quote(SECRET_MANAGER)}
source {bash_quote(SECRET_MENU)}
PROJECT_ROOT={bash_quote(project_root)}
DEPLOYMENT_PROFILE_ID=keycloak_only
PGADMIN_ENABLED=false
[ -z "$(_profile_batch_secret_names)" ]
! validate_profile_secret_values_file {bash_quote(values_file)}
"""
            completed = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Undeclared Docker secret key", completed.stderr)

    def test_batch_menu_requires_a_valid_profile_template(self) -> None:
        """Expose saved-file workflow only when exact names have a template.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(SECRET_MENU)}
PROJECT_ROOT={bash_quote(REPOSITORY_ROOT)}
DEPLOYMENT_PROFILE_ID=secure_messaging
profile_supports_secret_file_workflow
DEPLOYMENT_PROFILE_ID=felix
! profile_supports_secret_file_workflow
"""
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_keycloak_action_requires_a_supported_profile_contract(self) -> None:
        """Hide reconciliation when a profile cannot execute the adapter.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(KEYCLOAK_BOOTSTRAP)}
PROJECT_ROOT={bash_quote(REPOSITORY_ROOT)}
APP_CONFIG_FILE={bash_quote(REPOSITORY_ROOT / "site-configs" / "felix.json")}
profile_supports_keycloak_bootstrap
APP_CONFIG_FILE={bash_quote(REPOSITORY_ROOT / "site-configs" / "secure_messaging.json")}
! profile_supports_keycloak_bootstrap
"""
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_batch_allowlist_excludes_keycloak_client_credentials(self) -> None:
        """Keep confidential client secrets bootstrap/rotation-only.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(SECRET_MENU)}
PROJECT_ROOT={bash_quote(REPOSITORY_ROOT)}
APP_CONFIG_FILE={bash_quote(REPOSITORY_ROOT / "site-configs" / "felix.json")}
PGADMIN_ENABLED=false
names="$(_profile_batch_secret_names)"
printf '%s\\n' "$names"
printf '%s\\n' "$names" | grep -Fxq FELIX_DB_PASSWORD
! printf '%s\\n' "$names" |
    grep -Fxq FELIX_KEYCLOAK_ADMIN_CLIENT_SECRET
"""
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_internal_database_free_profile_still_shows_secrets(self) -> None:
        """Keep secret visibility independent from database capability.

        Returns:
            Nothing.
        """

        script = f"""
PROJECT_ROOT={bash_quote(REPOSITORY_ROOT)}
source {bash_quote(KEYCLOAK_BOOTSTRAP)}
source {bash_quote(SITE_HELPERS)}
source {bash_quote(MENU_HANDLERS)}
DEPLOYMENT_PROFILE_ID=secure_messaging
DB_TYPE=none
STACK_FAMILY=api
_profile_requires_secrets
"""
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_capability_only_secret_is_visible_during_setup(self) -> None:
        """Count enabled capability secrets even without base secrets.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary:
            profile_path = Path(temporary) / "capability.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "secrets": [],
                        "capabilities": {
                            "feature": {
                                "enabled": True,
                                "secretMounts": [{"name": "FEATURE_TOKEN"}],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            script = f"""
source {bash_quote(SITE_HELPERS)}
site_profile_declares_secrets {bash_quote(profile_path)}
"""
            completed = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)


def write_keycloak_only_profile_fixture(project_root: Path) -> Path:
    """Write an exact-name profile whose only secret is reconciliation-owned.

    Args:
        project_root: Temporary project root that receives the site profile,
            declared template, and populated values file.

    Returns:
        Path to the populated values file used by validation.

    Side Effects:
        Creates profile, template, and values files below ``project_root``.
    """

    profile_directory = project_root / "site-configs"
    template_directory = project_root / "setup" / "templates"
    profile_directory.mkdir(parents=True)
    template_directory.mkdir(parents=True)

    profile = {
        "secretsConfig": {
            "prefixed": False,
            "template": (
                "setup/templates/secrets.keycloak-only.env.template"
            ),
        },
        "secrets": ["ONLY_KEYCLOAK_CLIENT_SECRET"],
        "secretMounts": [
            {
                "name": "ONLY_KEYCLOAK_CLIENT_SECRET",
                "envKey": "KEYCLOAK_ADMIN_CLIENT_SECRET_FILE",
                "target": "/run/secrets/ONLY_KEYCLOAK_CLIENT_SECRET",
            }
        ],
    }
    (profile_directory / "keycloak_only.json").write_text(
        json.dumps(profile),
        encoding="utf-8",
    )
    (
        template_directory / "secrets.keycloak-only.env.template"
    ).write_text(
        "ONLY_KEYCLOAK_CLIENT_SECRET=\n",
        encoding="utf-8",
    )
    values_file = project_root / "secrets.env"
    values_file.write_text(
        "ONLY_KEYCLOAK_CLIENT_SECRET=value\n",
        encoding="utf-8",
    )
    return values_file


def bash_quote(path: Path) -> str:
    """Quote one filesystem path as a Bash word.

    Args:
        path: Path that may contain spaces or apostrophes.

    Returns:
        Single-quoted Bash representation.
    """

    return "'" + str(path).replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    unittest.main()
