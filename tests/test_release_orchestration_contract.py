"""
Tests for the Swarm-owned Felix release-orchestration contract.

The suite is dependency-free and verifies public deployment identity without
rendering a stack or reading an operator environment.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.felix_profile_fixture import PRODUCTION_PROFILE


CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "release_contracts"
    / "felix_swarm_contract.v1.json"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class FelixSwarmReleaseContractTests(unittest.TestCase):
    """Verifies candidate isolation, field ownership, and cutover safeguards."""

    def setUp(self) -> None:
        """Load a fresh contract object for each test.

        Returns:
            None.
        """

        self.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_candidate_and_legacy_deployments_are_distinct(self) -> None:
        """Ensure candidate and legacy identities cannot collapse together.

        Returns:
            None.
        """

        candidate = self.contract["candidate"]
        protection = self.contract["legacyProtection"]
        boundary = self.contract["deploymentBoundary"]

        self.assertEqual(candidate["webOrigin"], "https://felix-app.fe-wi.com")
        self.assertEqual(candidate["realm"], "felix-new")
        self.assertEqual(candidate["frontendClientId"], "felix-new-frontend")
        self.assertEqual(candidate["backendAudience"], "felix-new-backend")
        self.assertEqual(candidate["backendAdminClientId"], "felix-new-backend")
        self.assertNotEqual(boundary["candidateHost"], boundary["legacyHost"])
        self.assertNotIn(candidate["realm"], protection["protectedRealms"])

    def test_both_possible_legacy_realms_are_protected(self) -> None:
        """Ensure both known legacy realm names remain denylisted.

        Returns:
            None.
        """

        protected_realms = set(self.contract["legacyProtection"]["protectedRealms"])

        self.assertTrue({"felix", "felixappnew"}.issubset(protected_realms))

    def test_required_environment_and_secret_file_fields_are_declared(self) -> None:
        """Ensure public settings and secret-file ownership stay explicit.

        Returns:
            None.
        """

        environment_fields = set(self.contract["requiredEnvironmentFields"])
        secret_file_fields = self.contract["requiredSecretFileFields"]

        self.assertTrue(
            {
                "APP_PROFILE",
                "BACKEND_APP_ID",
                "AUTH_PROVIDER",
                "KEYCLOAK_ISSUER_URL",
                "KEYCLOAK_REALM",
            }.issubset(environment_fields)
        )
        self.assertEqual(secret_file_fields, ["KEYCLOAK_ADMIN_CLIENT_SECRET_FILE"])

    def test_guided_configuration_targets_one_full_stack(self) -> None:
        """Require normal root `.env` and the complete Felix service boundary.

        Returns:
            None.
        """

        configuration = self.contract["configurationInput"]
        services = self.contract["stackServices"]
        boundary = self.contract["deploymentBoundary"]

        self.assertEqual(
            self.contract["siteProfileDisplayName"],
            "Felix Backend and WebApp",
        )
        self.assertEqual(configuration["trackedExample"], ".env.example")
        self.assertEqual(configuration["wizardGenerated"], ".env")
        self.assertEqual(configuration["forbiddenRequiredInput"], "prod.env")
        self.assertEqual(set(services["required"]), {"web", "api", "redis"})
        self.assertEqual(
            set(services["databaseModes"]),
            {"local-postgresql", "external-postgresql-secret-file"},
        )
        self.assertEqual(services["optional"], ["pgadmin"])
        self.assertEqual(boundary["candidateStackName"], "felix-new")
        self.assertEqual(
            boundary["candidateApiHost"],
            "api.felix-app.fe-wi.com",
        )

    def test_forwarding_and_image_policy_fail_closed(self) -> None:
        """Ensure forwarding and mutable image deployment fail closed.

        Returns:
            None.
        """

        boundary = self.contract["deploymentBoundary"]

        self.assertIs(boundary["legacyForwardingRequiresCutoverApproval"], True)
        self.assertIs(boundary["mutableImageTagsAllowed"], False)

    def test_production_keycloak_owner_is_existing_swarm_deployment(self) -> None:
        """Reject the removed local-development checkout production boundary.

        Returns:
            None.
        """

        owner = self.contract["productionKeycloakOwner"]

        self.assertEqual(
            owner["repository"],
            "https://github.com/Sokrates1989/swarm-keycloak.git",
        )
        self.assertEqual(
            owner["deploymentPath"],
            "/swarm/administration/keycloak",
        )
        self.assertIs(
            owner["localDevelopmentRepositoryIsProductionDependency"],
            False,
        )
        self.assertIs(owner["separateToolCheckoutRequired"], False)

    def test_strict_felix_renderer_is_wired_into_shell_adapters(self) -> None:
        """Keep setup, direct build, and validation on one strict adapter.

        Returns:
            None.
        """

        expected_adapter = "scripts/felix_site_profile.py"
        sources = [
            (
                REPOSITORY_ROOT
                / "setup"
                / "modules"
                / "felix-setup-wizard.sh"
            ),
            REPOSITORY_ROOT / "scripts" / "build-site-stack.sh",
            REPOSITORY_ROOT / "scripts" / "validate-site.sh",
        ]

        for source in sources:
            content = source.read_text(encoding="utf-8")
            self.assertIn(expected_adapter, content, source)
            self.assertIn("--compose-check", content, source)

        setup_wizard = (
            REPOSITORY_ROOT / "setup" / "setup-wizard.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("run_guided_felix_setup", setup_wizard)

    def test_guided_wizard_owns_complete_public_schema_without_deploying(self) -> None:
        """Keep every public field in the menu flow and runtime effects separate.

        Returns:
            None.
        """

        wizard = (
            REPOSITORY_ROOT
            / "setup"
            / "modules"
            / "felix-setup-wizard.sh"
        ).read_text(encoding="utf-8")

        for key in PRODUCTION_PROFILE:
            self.assertIn(f"{key}=", wizard, key)
        self.assertIn("--force", wizard)
        self.assertIn("render --compose-check", wizard)
        self.assertNotIn("docker stack deploy", wizard)
        self.assertNotIn("prod.env", wizard)

    def test_keycloak_menu_uses_existing_production_owner(self) -> None:
        """Route Felix to the deployed swarm-keycloak owner without an adapter.

        Returns:
            None.
        """

        quick_start = (REPOSITORY_ROOT / "quick-start.sh").read_text(
            encoding="utf-8"
        )
        menu_handlers = (
            REPOSITORY_ROOT / "setup" / "modules" / "menu_handlers.sh"
        ).read_text(encoding="utf-8")
        keycloak_owner = (
            REPOSITORY_ROOT
            / "setup"
            / "modules"
            / "felix-production-keycloak.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'source "${PROJECT_ROOT}/setup/modules/felix-production-keycloak.sh"',
            quick_start,
        )
        self.assertIn("show_felix_production_keycloak_handoff", menu_handlers)
        self.assertIn("/swarm/administration/keycloak", keycloak_owner)
        self.assertIn("swarm-keycloak.git", keycloak_owner)
        self.assertNotIn("FELIX_KEYCLOAK_TOOL_DIRECTORY", keycloak_owner)
        self.assertNotIn("scripts/felix_keycloak_adapter.py", quick_start)
        self.assertNotIn("KEYCLOAK_CLIENT_SECRET=", keycloak_owner)
        self.assertFalse(
            (REPOSITORY_ROOT / "scripts" / "felix_keycloak_adapter.py").exists()
        )
        self.assertFalse(
            (
                REPOSITORY_ROOT
                / "setup"
                / "modules"
                / "felix-keycloak-release.sh"
            ).exists()
        )

    def test_candidate_menu_uses_only_strict_release_state_machine(self) -> None:
        """Route candidate deploy, health, and logs through one strict CLI.

        Returns:
            None.
        """

        quick_start = (REPOSITORY_ROOT / "quick-start.sh").read_text(
            encoding="utf-8"
        )
        menu_handlers = (
            REPOSITORY_ROOT / "setup" / "modules" / "menu_handlers.sh"
        ).read_text(encoding="utf-8")
        release_menu = (
            REPOSITORY_ROOT / "setup" / "modules" / "felix-release.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'source "${PROJECT_ROOT}/setup/modules/felix-release.sh"',
            quick_start,
        )
        self.assertIn("felix_release_menu", menu_handlers)
        self.assertIn("_felix_release_run status", menu_handlers)
        self.assertIn("_felix_release_run logs", menu_handlers)
        self.assertIn("scripts/felix_deploy.py", release_menu)
        self.assertIn("_felix_release_run drill-rollback", release_menu)
        self.assertIn("_felix_release_run rollback", release_menu)

    def test_root_env_reloads_strict_candidate_identity(self) -> None:
        """Keep the strict Felix gate populated after setup returns.

        The setup wizard runs as a child process. The parent quick-start menu
        therefore has to reload every public identity field materialized into
        the root ``.env`` before deciding which deployment menus are safe.

        Returns:
            None.
        """

        site_helpers = (
            REPOSITORY_ROOT / "setup" / "modules" / "site_helpers.sh"
        ).read_text(encoding="utf-8")

        for field in (
            "APP_PROFILE",
            "BACKEND_APP_ID",
            "AUTH_PROVIDER",
            "KEYCLOAK_ISSUER_URL",
            "KEYCLOAK_REALM",
            "KEYCLOAK_AUDIENCE",
        ):
            self.assertIn(
                f'export {field}="$(_root_env_value "$env_file" {field})"',
                site_helpers,
                field,
            )

    def test_candidate_secret_menu_preserves_exact_ownership(self) -> None:
        """Expose the database editor and production Keycloak owner handoff.

        Returns:
            None.
        """

        quick_start = (REPOSITORY_ROOT / "quick-start.sh").read_text(
            encoding="utf-8"
        )
        menu_handlers = (
            REPOSITORY_ROOT / "setup" / "modules" / "menu_handlers.sh"
        ).read_text(encoding="utf-8")
        secret_menu = (
            REPOSITORY_ROOT
            / "setup"
            / "modules"
            / "docker-secrets-menu.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'source "${PROJECT_ROOT}/setup/modules/docker-secrets-menu.sh"',
            quick_start,
        )
        self.assertIn("manage_docker_secrets_menu", menu_handlers)
        self.assertIn('"FELIX_NEW_DB_PASSWORD"', secret_menu)
        self.assertIn(
            '"FELIX_NEW_KEYCLOAK_ADMIN_CLIENT_SECRET"',
            secret_menu,
        )
        self.assertIn('"FELIX_NEW_PGADMIN_PASSWORD"', secret_menu)
        self.assertIn(
            '_create_felix_editor_secret "FELIX_NEW_DB_PASSWORD"',
            secret_menu,
        )
        self.assertNotIn(
            'create_single_secret "FELIX_NEW_KEYCLOAK_ADMIN_CLIENT_SECRET"',
            secret_menu,
        )
        self.assertIn(
            "show_felix_production_keycloak_handoff",
            secret_menu,
        )
        self.assertIn(
            'db_password_secret="${prefix_upper}_DB_PASSWORD"',
            secret_menu,
        )


if __name__ == "__main__":
    unittest.main()
