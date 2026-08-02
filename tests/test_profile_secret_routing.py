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
NATIVE_BASH_AVAILABLE = (
    not sys.platform.startswith("win")
    and shutil.which("bash") is not None
)
NATIVE_BASH_AND_JQ = (
    NATIVE_BASH_AVAILABLE
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

    def test_felix_declares_generated_secret_value_guidance(self) -> None:
        """Drive Felix's batch editor from profile data without custom code.

        Returns:
            Nothing.
        """

        profile = json.loads(
            (REPOSITORY_ROOT / "site-configs" / "felix.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertNotIn("template", profile["secretsConfig"])
        self.assertIn(
            "FELIX_DB_PASSWORD",
            profile["secretsConfig"]["valueHelp"],
        )
        self.assertNotIn(
            "FELIX_KEYCLOAK_ADMIN_CLIENT_SECRET",
            profile["secretsConfig"]["valueHelp"],
        )

    def test_secret_menus_do_not_route_by_renderer_or_database(self) -> None:
        """Reject the former schema and DB-type shortcuts.

        Returns:
            Nothing.
        """

        secret_source = SECRET_MENU.read_text(encoding="utf-8")
        menu_source = MENU_HANDLERS.read_text(encoding="utf-8")
        requires = menu_source[
            menu_source.index("_profile_requires_secrets()")
            : menu_source.index("# show_main_menu")
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

    def test_legacy_secret_menu_uses_the_profile_batch_adapter(self) -> None:
        """Apply required-value and deletion policy to prefixed profiles too.

        Returns:
            Nothing.
        """

        source = SECRET_MENU.read_text(encoding="utf-8")
        legacy_menu = source[
            source.index("_manage_legacy_docker_secrets()") : source.index(
                "# manage_docker_secrets_menu"
            )
        ]

        self.assertIn("create_profile_secrets_from_env_file", legacy_menu)
        self.assertNotIn("create_secrets_from_env_file", legacy_menu)

    def test_keycloak_failures_are_not_silently_discarded(self) -> None:
        """Require menu call sites to report rather than erase failures.

        Returns:
            Nothing.
        """

        secret_source = SECRET_MENU.read_text(encoding="utf-8")
        menu_source = MENU_HANDLERS.read_text(encoding="utf-8")

        self.assertNotIn(
            "run_profile_keycloak_bootstrap || true",
            secret_source,
        )
        self.assertNotIn(
            "run_profile_keycloak_bootstrap || true",
            menu_source,
        )
        self.assertIn(
            "Keycloak bootstrap did not complete",
            secret_source,
        )
        self.assertIn(
            "Keycloak bootstrap did not complete",
            menu_source,
        )


@unittest.skipUnless(
    NATIVE_BASH_AVAILABLE,
    "Failure-propagation integration requires native Bash.",
)
class ProfileSecretFailurePropagationLinuxTests(unittest.TestCase):
    """Exercise Keycloak failure propagation without requiring jq."""

    def test_failed_keycloak_bootstrap_is_returned_on_menu_exit(self) -> None:
        """Preserve a bootstrap failure so full deploy cannot continue.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(SECRET_MENU)}
_show_profile_secret_status() {{ :; }}
profile_supports_secret_file_workflow() {{ return 1; }}
profile_supports_keycloak_bootstrap() {{ return 0; }}
run_profile_keycloak_bootstrap() {{
    echo bootstrap-failed
    return 23
}}
run_profile_keycloak_secret_rotation() {{ return 24; }}
list_docker_secrets() {{ :; }}
_manage_profile_docker_secrets <<< $'3\\n0\\n'
status=$?
printf 'STATUS=%s\\n' "$status"
[ "$status" -eq 23 ]
"""
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("bootstrap-failed", completed.stdout)
        self.assertIn("Keycloak bootstrap did not complete", completed.stdout)
        self.assertIn("STATUS=23", completed.stdout)

    def test_secret_chooser_prints_menu_before_reading_selection(self) -> None:
        """Keep menu rendering outside the selected-value assignment channel.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(SECRET_MENU)}
selected=''
_select_profile_secret selected required $'FIRST_SECRET\nSECOND_SECRET' <<< '2'
printf 'SELECTED=%s\n' "$selected"
"""
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("1) FIRST_SECRET", completed.stdout)
        self.assertIn("2) SECOND_SECRET", completed.stdout)
        self.assertIn("SELECTED=SECOND_SECRET", completed.stdout)

    def test_successful_batch_import_deletes_temporary_values_file(self) -> None:
        """Delete secret plaintext immediately after all creations succeed.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary:
            values_file = Path(temporary) / "secrets.env"
            template_file = Path(temporary) / "secrets.env.template"
            values_file.write_text("REQUIRED_SECRET=value\n", encoding="utf-8")
            template_file.write_text(
                "REQUIRED_SECRET=\n",
                encoding="utf-8",
            )
            script = f"""
source {bash_quote(SECRET_MANAGER)}
choose_editor() {{ SELECTED_EDITOR=true; }}
create_secret_from_value() {{
    CREATE_SECRET_FROM_VALUE_ACTION=created
    return 0
}}
create_secrets_from_env_file \
    {bash_quote(values_file)} \
    {bash_quote(template_file)} \
    '' \
    REQUIRED_SECRET \
    true \
    always \
    REQUIRED_SECRET <<< ''
[ ! -e {bash_quote(values_file)} ]
"""
            completed = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "Deleted temporary secret values file",
            completed.stdout,
        )
        self.assertIn("including after validation/import errors", completed.stdout)

    def test_failed_batch_import_deletes_temporary_values_file(self) -> None:
        """Delete ephemeral plaintext when any Docker creation fails.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary:
            values_file = Path(temporary) / "secrets.env"
            template_file = Path(temporary) / "secrets.env.template"
            values_file.write_text("REQUIRED_SECRET=value\n", encoding="utf-8")
            template_file.write_text(
                "REQUIRED_SECRET=\n",
                encoding="utf-8",
            )
            script = f"""
source {bash_quote(SECRET_MANAGER)}
choose_editor() {{ SELECTED_EDITOR=true; }}
create_secret_from_value() {{ return 1; }}
! create_secrets_from_env_file \
    {bash_quote(values_file)} \
    {bash_quote(template_file)} \
    '' \
    REQUIRED_SECRET \
    true \
    always \
    REQUIRED_SECRET <<< ''
[ ! -e {bash_quote(values_file)} ]
"""
            completed = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(values_file.exists())
        self.assertIn("Deleted temporary secret values file", completed.stdout)

    def test_validation_failure_deletes_temporary_values_file(self) -> None:
        """Delete an ephemeral file rejected for an undeclared secret key.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary:
            values_file = Path(temporary) / "secrets.env"
            template_file = Path(temporary) / "secrets.env.template"
            values_file.write_text("UNDECLARED_SECRET=value\n", encoding="utf-8")
            template_file.write_text("REQUIRED_SECRET=\n", encoding="utf-8")
            script = f"""
source {bash_quote(SECRET_MANAGER)}
choose_editor() {{ SELECTED_EDITOR=true; }}
create_secret_from_value() {{ echo MUTATION_MUST_NOT_RUN; return 0; }}
! create_secrets_from_env_file \
    {bash_quote(values_file)} \
    {bash_quote(template_file)} \
    '' \
    REQUIRED_SECRET \
    true \
    always \
    REQUIRED_SECRET <<< ''
[ ! -e {bash_quote(values_file)} ]
"""
            completed = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(values_file.exists())
        self.assertIn("Undeclared Docker secret key", completed.stderr)
        self.assertIn("Deleted temporary secret values file", completed.stdout)
        self.assertNotIn("MUTATION_MUST_NOT_RUN", completed.stdout)

    def test_failed_saved_import_keeps_non_ephemeral_values_file(self) -> None:
        """Preserve an explicit restore input when Docker creation fails.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary:
            values_file = Path(temporary) / "saved-secrets.env"
            template_file = Path(temporary) / "secrets.env.template"
            values_file.write_text("REQUIRED_SECRET=value\n", encoding="utf-8")
            template_file.write_text("REQUIRED_SECRET=\n", encoding="utf-8")
            script = f"""
source {bash_quote(SECRET_MANAGER)}
choose_editor() {{ SELECTED_EDITOR=true; }}
create_secret_from_value() {{ return 1; }}
! create_secrets_from_env_file \
    {bash_quote(values_file)} \
    {bash_quote(template_file)} \
    '' \
    REQUIRED_SECRET \
    true \
    keep \
    REQUIRED_SECRET <<< ''
[ -e {bash_quote(values_file)} ]
"""
            completed = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(values_file.exists())
        self.assertIn("retained for correction or restore retry", completed.stdout)

    def test_editor_failure_deletes_temporary_values_file(self) -> None:
        """Delete ephemeral plaintext when the selected editor fails.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary:
            values_file = Path(temporary) / "secrets.env"
            template_file = Path(temporary) / "secrets.env.template"
            values_file.write_text("REQUIRED_SECRET=value\n", encoding="utf-8")
            template_file.write_text("REQUIRED_SECRET=\n", encoding="utf-8")
            script = f"""
source {bash_quote(SECRET_MANAGER)}
choose_editor() {{ SELECTED_EDITOR=false; }}
! create_secrets_from_env_file \
    {bash_quote(values_file)} \
    {bash_quote(template_file)} \
    '' \
    REQUIRED_SECRET \
    true \
    always \
    REQUIRED_SECRET <<< ''
[ ! -e {bash_quote(values_file)} ]
"""
            completed = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(values_file.exists())
        self.assertIn("Editor exited", completed.stderr)
        self.assertIn("Deleted temporary secret values file", completed.stdout)

    def test_interrupt_deletes_temporary_values_file_before_exit(self) -> None:
        """Delete ephemeral plaintext before propagating an operator abort.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary:
            values_file = Path(temporary) / "secrets.env"
            template_file = Path(temporary) / "secrets.env.template"
            values_file.write_text("REQUIRED_SECRET=value\n", encoding="utf-8")
            template_file.write_text("REQUIRED_SECRET=\n", encoding="utf-8")
            script = f"""
source {bash_quote(SECRET_MANAGER)}
interrupt_editor() {{ kill -INT "$$"; }}
choose_editor() {{ SELECTED_EDITOR=interrupt_editor; }}
create_secrets_from_env_file \
    {bash_quote(values_file)} \
    {bash_quote(template_file)} \
    '' \
    REQUIRED_SECRET \
    true \
    always \
    REQUIRED_SECRET <<< ''
"""
            completed = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 130, completed.stderr)
            self.assertFalse(values_file.exists())
        self.assertIn("Secret-file workflow interrupted", completed.stderr)
        self.assertIn("Deleted temporary secret values file", completed.stdout)


@unittest.skipUnless(
    NATIVE_BASH_AND_JQ,
    "Secret-routing integration requires native Bash and jq.",
)
class ProfileSecretRoutingLinuxTests(unittest.TestCase):
    """Exercise exact secret template routing with the real Bash module."""

    def test_prefixed_profile_batch_requires_all_declared_values(self) -> None:
        """Preserve legacy prefixes while enforcing profile-required keys.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(SECRET_MENU)}
create_secrets_from_env_file() {{
    printf 'PREFIX=%s\nDELETE=%s\nREQUIRED=%s\n' "$3" "$6" "$7"
}}
PROJECT_ROOT={bash_quote(REPOSITORY_ROOT)}
DEPLOYMENT_PROFILE_ID=demo_app
STACK_NAME=demo-app
create_profile_secrets_from_env_file /tmp/demo-secrets.env
"""
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("PREFIX=DEMO_APP", completed.stdout)
        self.assertIn("DELETE=always", completed.stdout)
        self.assertIn("DB_PASSWORD", completed.stdout)
        self.assertIn("ADMIN_API_KEY", completed.stdout)
        self.assertIn("BACKUP_RESTORE_API_KEY", completed.stdout)
        self.assertIn("BACKUP_DELETE_API_KEY", completed.stdout)

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

    def test_batch_menu_supports_static_or_generated_profile_templates(
        self,
    ) -> None:
        """Expose static and config-generated exact-name file workflows.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(SECRET_MENU)}
PROJECT_ROOT={bash_quote(REPOSITORY_ROOT)}
DEPLOYMENT_PROFILE_ID=secure_messaging
profile_supports_secret_file_workflow
DEPLOYMENT_PROFILE_ID=felix
profile_supports_secret_file_workflow
"""
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_felix_generated_template_is_complete_and_excludes_keycloak(
        self,
    ) -> None:
        """Generate required and optional Felix entries solely from its profile.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "generated-secrets.env"
            script = f"""
source {bash_quote(SECRET_MENU)}
PROJECT_ROOT={bash_quote(REPOSITORY_ROOT)}
DEPLOYMENT_PROFILE_ID=felix
PGADMIN_ENABLED=true
_write_generated_profile_secrets_template {bash_quote(destination)}
cat {bash_quote(destination)}
"""
            completed = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("FELIX_DB_PASSWORD=", completed.stdout)
        self.assertIn("FELIX_PGADMIN_PASSWORD=", completed.stdout)
        self.assertIn("FELIX_AI_CHAT_API_KEY=", completed.stdout)
        self.assertIn("FELIX_WEB_PUSH_VAPID_PRIVATE_KEY=", completed.stdout)
        self.assertNotIn(
            "FELIX_KEYCLOAK_ADMIN_CLIENT_SECRET=",
            completed.stdout,
        )
        self.assertIn("This temporary file is always deleted", completed.stdout)
        self.assertIn("after validation/import errors", completed.stdout)

    def test_required_batch_values_are_rejected_before_mutation(self) -> None:
        """Reject an empty required entry before any Docker mutation.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary:
            values_file = Path(temporary) / "secrets.env"
            values_file.write_text(
                "REQUIRED_ONE=\nOPTIONAL_ONE=value\n",
                encoding="utf-8",
            )
            script = f"""
source {bash_quote(SECRET_MANAGER)}
! _validate_required_secret_env_values \
    {bash_quote(values_file)} \
    REQUIRED_ONE
"""
            completed = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("Required Docker secret value is empty", completed.stderr)

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
