"""
Module: test_legacy_admin_ui.py

Description:
    Protects schema-3 database-management rendering, proxy-mode separation,
    and legacy Docker-secret naming. Static tests run on every host; focused
    stack builds run when native Bash and jq are available.

Dependencies:
    - Python standard library.
    - Bash and jq for Linux integration coverage.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LEGACY_ENVIRONMENT = (
    REPOSITORY_ROOT / "setup" / "modules" / "legacy-profile-environment.sh"
)
BUILD_SCRIPT = REPOSITORY_ROOT / "scripts" / "build-site-stack.sh"
SECRET_MENU = (
    REPOSITORY_ROOT / "setup" / "modules" / "docker-secrets-menu.sh"
)
PGADMIN_MODULE = (
    REPOSITORY_ROOT / "setup" / "compose-modules" / "pgadmin-local.yml"
)
MONGO_EXPRESS_MODULE = (
    REPOSITORY_ROOT
    / "setup"
    / "compose-modules"
    / "mongo-express-local.yml"
)
TRAEFIK_LABEL_SNIPPETS = (
    REPOSITORY_ROOT
    / "setup"
    / "compose-modules"
    / "snippets"
    / "proxy-traefik-direct-ssl.labels.yml",
    REPOSITORY_ROOT
    / "setup"
    / "compose-modules"
    / "snippets"
    / "proxy-traefik-proxy-ssl.labels.yml",
    REPOSITORY_ROOT
    / "setup"
    / "compose-modules"
    / "snippets"
    / "admin-traefik-direct.labels.yml",
    REPOSITORY_ROOT
    / "setup"
    / "compose-modules"
    / "snippets"
    / "admin-traefik-proxy.labels.yml",
    REPOSITORY_ROOT
    / "setup"
    / "compose-modules"
    / "nginx"
    / "snippets"
    / "proxy-traefik-direct-ssl.labels.yml",
    REPOSITORY_ROOT
    / "setup"
    / "compose-modules"
    / "nginx"
    / "snippets"
    / "proxy-traefik-proxy-ssl.labels.yml",
)


class LegacyAdminUiStaticTests(unittest.TestCase):
    """Verify profile and source contracts without requiring Bash."""

    def test_legacy_writer_persists_admin_toggle_and_direct_port(self) -> None:
        """Keep the collector result available to the generic renderer.

        Returns:
            Nothing.
        """

        source = LEGACY_ENVIRONMENT.read_text(encoding="utf-8")

        self.assertIn(
            'echo "PGADMIN_ENABLED=${PGADMIN_ENABLED:-false}"',
            source,
        )
        self.assertIn(
            'echo "PGADMIN_PUBLISHED_PORT=${PGADMIN_PUBLISHED_PORT:-5054}"',
            source,
        )
        self.assertIn("_legacy_environment_admin_secret_name()", source)
        self.assertIn("MONGO_EXPRESS_USERNAME=", source)

    def test_admin_ui_secret_association_is_explicit_profile_data(self) -> None:
        """Require each legacy admin UI to name its own declared secret.

        Returns:
            Nothing.
        """

        for config_id in ("postgres_template", "mongodb_template"):
            profile_path = (
                REPOSITORY_ROOT / "site-configs" / f"{config_id}.json"
            )
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
            admin_ui = profile["adminUI"]

            self.assertEqual(admin_ui["secret"], "DB_UI_ADMIN_PASSWORD")
            self.assertIn(admin_ui["secret"], profile["secrets"])

    def test_secret_prefix_normalization_matches_the_shared_menu(self) -> None:
        """Preserve separators instead of collapsing distinct stack names.

        Returns:
            Nothing.
        """

        source = BUILD_SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("tr -d '_'", source)
        self.assertIn("PROFILE_ADMIN_UI_SECRET", source)
        self.assertIn(
            'DB_UI_ADMIN_PASSWORD_SECRET="${PREFIX_UPPER}_${PROFILE_ADMIN_UI_SECRET}"',
            source,
        )

    def test_admin_modules_declare_proxy_mode_boundaries(self) -> None:
        """Keep direct ports and Traefik-only sections mutually selectable.

        Returns:
            Nothing.
        """

        for module in (PGADMIN_MODULE, MONGO_EXPRESS_MODULE):
            source = module.read_text(encoding="utf-8")

            self.assertIn("###ADMIN_TRAEFIK_NETWORK_START###", source)
            self.assertIn("###ADMIN_DIRECT_PORTS_START###", source)
            self.assertIn("###ADMIN_TRAEFIK_LABELS_START###", source)
            self.assertIn("      - backend", source)

        mongo = MONGO_EXPRESS_MODULE.read_text(encoding="utf-8")
        self.assertNotIn("XXX_CHANGE_ME_MONGODB_PASSWORD_XXX", mongo)

    def test_interactive_secret_flow_includes_only_enabled_admin_ui(self) -> None:
        """Pass the profile-associated admin secret to interactive creation.

        Returns:
            Nothing.
        """

        source = SECRET_MENU.read_text(encoding="utf-8")

        self.assertIn("_legacy_admin_ui_secret_name()", source)
        self.assertIn('"${PGADMIN_ENABLED:-false}" != "true"', source)
        self.assertIn(".adminUI.secret // empty", source)
        self.assertIn('"$db_ui_admin_password_secret"', source)

    def test_generic_labels_do_not_infer_constraint_from_network(self) -> None:
        """Use the dedicated provider label in every generic service family.

        Returns:
            Nothing.
        """

        for snippet in TRAEFIK_LABEL_SNIPPETS:
            source = snippet.read_text(encoding="utf-8")

            self.assertIn(
                "traefik.constraint-label=${TRAEFIK_CONSTRAINT_LABEL}",
                source,
                str(snippet),
            )
            self.assertNotIn(
                "traefik.constraint-label=traefik-public",
                source,
                str(snippet),
            )


@unittest.skipUnless(
    not sys.platform.startswith("win")
    and shutil.which("bash") is not None
    and shutil.which("jq") is not None,
    "Legacy compose integration requires native Bash and jq.",
)
class LegacyAdminUiLinuxIntegrationTests(unittest.TestCase):
    """Render disposable schema-3 stacks through the production Bash path."""

    def setUp(self) -> None:
        """Create a minimal disposable copy of the generic renderer tree.

        Returns:
            Nothing.
        """

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        for directory in ("scripts", "setup", "site-configs"):
            shutil.copytree(
                REPOSITORY_ROOT / directory,
                self.root / directory,
            )

    def tearDown(self) -> None:
        """Remove the disposable renderer tree.

        Returns:
            Nothing.
        """

        self.temporary_directory.cleanup()

    def _environment(
        self,
        config_id: str,
        database_type: str,
        proxy_type: str,
        admin_enabled: bool,
    ) -> str:
        """Build one public legacy environment fixture.

        Args:
            config_id: Selected site-config filename stem.
            database_type: postgresql or mongodb.
            proxy_type: traefik or none.
            admin_enabled: Whether the profile-declared admin UI is selected.

        Returns:
            Newline-terminated public environment text.
        """

        values = {
            "DEPLOYMENT_PROFILE_ID": config_id,
            "APP_ID": config_id,
            "BACKEND_APP_ID": config_id,
            "STACK_NAME": "template_app",
            "STACK_FAMILY": "api",
            "STACK_ROLE": "api",
            "PRIMARY_SERVICE": "api",
            "DOMAIN": "api.example.com",
            "API_URL": "api.example.com",
            "DB_TYPE": database_type,
            "DB_MODE": "local",
            "DB_HOST": "postgres" if database_type == "postgresql" else "mongodb",
            "DB_PORT": "5432" if database_type == "postgresql" else "27017",
            "DB_NAME": "template_db",
            "DB_USER": "template_user",
            "POSTGRES_DB": "template_db",
            "POSTGRES_USER": "template_user",
            "POSTGRES_REPLICAS": "1",
            "MONGODB_DB": "template_db",
            "MONGODB_USER": "template_user",
            "MONGODB_REPLICAS": "1",
            "PROXY_TYPE": proxy_type,
            "SSL_MODE": "proxy",
            "TRAEFIK_NETWORK": (
                "shared-edge-overlay" if proxy_type == "traefik" else ""
            ),
            "TRAEFIK_CONSTRAINT_LABEL": (
                "traefik-public-provider"
                if proxy_type == "traefik"
                else ""
            ),
            "TRAEFIK_CERT_RESOLVER": "le",
            "IMAGE_NAME": f"sokrates1989/python-api-{config_id}",
            "IMAGE_VERSION": "1.2.3",
            "PORT": "8080",
            "PUBLISHED_PORT": "8083",
            "API_REPLICAS": "1",
            "REDIS_REPLICAS": "1",
            "MEMORY_LIMIT": "512M",
            "DATA_ROOT": "/swarm/volumes/template_app",
            "SECRETS_PREFIX": "template_app",
            "PGADMIN_ENABLED": str(admin_enabled).lower(),
            "PGADMIN_URL": "admin.api.example.com",
            "PGADMIN_DOMAIN": "admin.api.example.com",
            "PGADMIN_EMAIL": "admin@example.com",
            "PGADMIN_REPLICAS": "1",
            "PGADMIN_PUBLISHED_PORT": "5054",
            "MONGO_EXPRESS_URL": "admin.api.example.com",
            "MONGO_EXPRESS_USER": "dbadmin",
            "MONGO_EXPRESS_REPLICAS": "1",
        }
        return "".join(f"{key}={value}\n" for key, value in values.items())

    def _render(
        self,
        config_id: str,
        database_type: str,
        proxy_type: str,
        admin_enabled: bool,
    ) -> str:
        """Run the production generic builder and return its rendered stack.

        Args:
            config_id: Selected site-config filename stem.
            database_type: postgresql or mongodb.
            proxy_type: traefik or none.
            admin_enabled: Whether the admin UI should be rendered.

        Returns:
            Rendered swarm-stack.yml text.

        Raises:
            AssertionError: If the production build script fails.
        """

        environment = self._environment(
            config_id,
            database_type,
            proxy_type,
            admin_enabled,
        )
        (self.root / ".env").write_text(environment, encoding="utf-8")
        completed = subprocess.run(
            ["bash", str(self.root / "scripts" / "build-site-stack.sh")],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return (self.root / "swarm-stack.yml").read_text(encoding="utf-8")

    def _write_admin_environment(self, admin_enabled: bool) -> str:
        """Run the legacy admin environment writer with normalized answers.

        Args:
            admin_enabled: Whether the operator enabled pgAdmin.

        Returns:
            Generated database-management environment fragment.

        Raises:
            AssertionError: If the legacy writer fails.
        """

        destination = self.root / "admin.env"
        command = (
            'source "$LEGACY_ENVIRONMENT"; '
            ': > "$ADMIN_ENV_DESTINATION"; '
            '_write_legacy_admin_environment "$ADMIN_ENV_DESTINATION"'
        )
        environment = {
            **os.environ,
            "LEGACY_ENVIRONMENT": str(
                self.root
                / "setup"
                / "modules"
                / "legacy-profile-environment.sh"
            ),
            "ADMIN_ENV_DESTINATION": str(destination),
            "APP_ADMIN_UI_TYPE": "pgadmin",
            "APP_ADMIN_UI_SECRET": "DB_UI_ADMIN_PASSWORD",
            "DB_MODE": "local",
            "PGADMIN_ENABLED": str(admin_enabled).lower(),
            "PGADMIN_PUBLISHED_PORT": "5054",
            "PGADMIN_DOMAIN": "admin.api.example.com",
            "PGADMIN_REPLICAS": "1",
            "PGADMIN_EMAIL": "admin@example.com",
            "SECRET_PREFIX": "template_app",
        }
        completed = subprocess.run(
            ["bash", "-c", command],
            cwd=self.root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return destination.read_text(encoding="utf-8")

    def _interactive_secret_arguments(self, admin_enabled: bool) -> str:
        """Capture arguments sent by legacy secret-menu option 2.

        Args:
            admin_enabled: Whether the admin UI capability is active.

        Returns:
            Stubbed secret-creation argument evidence.

        Raises:
            AssertionError: If the isolated menu invocation fails.
        """

        command = (
            'source "$SECRET_MENU"; '
            "_secret_status_line() { return 0; }; "
            "_require_stopped_stack_for_secret_change() { return 0; }; "
            "create_docker_secrets() { "
            'printf "COUNT=%s\\nLAST=%s\\n" "$#" "${5:-}"; '
            "}; "
            "_manage_legacy_docker_secrets"
        )
        environment = {
            **os.environ,
            "SECRET_MENU": str(
                self.root
                / "setup"
                / "modules"
                / "docker-secrets-menu.sh"
            ),
            "SECRET_PREFIX": "template_app",
            "STACK_NAME": "template_app",
            "PGADMIN_ENABLED": str(admin_enabled).lower(),
            "APP_ADMIN_UI_SECRET": "DB_UI_ADMIN_PASSWORD",
        }
        completed = subprocess.run(
            ["bash", "-c", command],
            cwd=self.root,
            env=environment,
            input="2\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout

    def test_interactive_secret_option_tracks_enabled_admin_ui(self) -> None:
        """Create the admin secret only when its service is rendered.

        Returns:
            Nothing.
        """

        enabled = self._interactive_secret_arguments(True)
        disabled = self._interactive_secret_arguments(False)

        self.assertIn("COUNT=5\n", enabled)
        self.assertIn("LAST=TEMPLATE_APP_DB_UI_ADMIN_PASSWORD\n", enabled)
        self.assertIn("COUNT=5\n", disabled)
        self.assertIn("LAST=\n", disabled)

    def test_writer_persists_enabled_and_disabled_admin_state(self) -> None:
        """Persist the toggle while omitting disabled credentials and mounts.

        Returns:
            Nothing.
        """

        enabled = self._write_admin_environment(True)
        disabled = self._write_admin_environment(False)

        self.assertIn("PGADMIN_ENABLED=true\n", enabled)
        self.assertIn("PGADMIN_PUBLISHED_PORT=5054\n", enabled)
        self.assertIn(
            "PGADMIN_PASSWORD_FILE="
            "/run/secrets/TEMPLATE_APP_DB_UI_ADMIN_PASSWORD\n",
            enabled,
        )
        self.assertIn("PGADMIN_ENABLED=false\n", disabled)
        self.assertNotIn("PGADMIN_PASSWORD_FILE=", disabled)

    def test_disabled_pgadmin_omits_service_and_secret(self) -> None:
        """Omit disabled profile capabilities and their unused secret.

        Returns:
            Nothing.
        """

        stack = self._render(
            "postgres_template",
            "postgresql",
            "none",
            False,
        )

        self.assertNotIn("\n  pgadmin:\n", stack)
        self.assertNotIn("TEMPLATE_APP_DB_UI_ADMIN_PASSWORD", stack)
        self.assertNotIn("XXX_CHANGE_ME", stack)

    def test_direct_pgadmin_publishes_port_without_traefik(self) -> None:
        """Render direct pgAdmin with backend connectivity and exact secrets.

        Returns:
            Nothing.
        """

        stack = self._render(
            "postgres_template",
            "postgresql",
            "none",
            True,
        )

        self.assertIn("\n  pgadmin:\n", stack)
        self.assertIn("published: ${PGADMIN_PUBLISHED_PORT}", stack)
        self.assertIn("target: 5050", stack)
        self.assertNotIn("traefik.", stack)
        self.assertIn("TEMPLATE_APP_DB_PASSWORD", stack)
        self.assertIn("TEMPLATE_APP_DB_UI_ADMIN_PASSWORD", stack)
        self.assertNotIn("TEMPLATEAPP_", stack)
        self.assertNotIn("XXX_CHANGE_ME", stack)
        self.assertNotIn("###ADMIN_", stack)

    def test_direct_mongo_express_uses_database_secret_and_port(self) -> None:
        """Render direct Mongo Express without its obsolete secret placeholder.

        Returns:
            Nothing.
        """

        stack = self._render(
            "mongodb_template",
            "mongodb",
            "none",
            True,
        )

        self.assertIn("\n  mongo-express:\n", stack)
        self.assertIn("published: ${PGADMIN_PUBLISHED_PORT}", stack)
        self.assertIn("target: 8081", stack)
        self.assertIn(
            "/run/secrets/TEMPLATE_APP_DB_PASSWORD",
            stack,
        )
        self.assertNotIn("traefik.", stack)
        self.assertNotIn("XXX_CHANGE_ME", stack)
        self.assertNotIn("###ADMIN_", stack)

    def test_traefik_pgadmin_has_labels_without_direct_port(self) -> None:
        """Render Traefik-only pgAdmin routing from the same service module.

        Returns:
            Nothing.
        """

        stack = self._render(
            "postgres_template",
            "postgresql",
            "traefik",
            True,
        )

        self.assertIn("\n  pgadmin:\n", stack)
        self.assertIn("shared-edge-overlay:", stack)
        self.assertIn(
            "traefik.http.routers.${STACK_NAME}_pgadmin.rule",
            stack,
        )
        self.assertIn("traefik.docker.network=${TRAEFIK_NETWORK}", stack)
        self.assertIn(
            "traefik.constraint-label=${TRAEFIK_CONSTRAINT_LABEL}",
            stack,
        )
        self.assertNotIn("traefik.constraint-label=shared-edge-overlay", stack)
        self.assertIn("${STACK_NAME}_pgadmin_protoheader", stack)
        self.assertNotIn("published: ${PGADMIN_PUBLISHED_PORT}", stack)
        self.assertNotIn("XXX_CHANGE_ME", stack)
        self.assertNotIn("###ADMIN_", stack)


if __name__ == "__main__":
    unittest.main()
