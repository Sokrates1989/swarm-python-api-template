"""
Module: test_release_orchestration_contract.py

Description:
    Verifies the secret-free Felix release identity and, critically, the
    architectural rule that production behavior is selected through site
    profile capabilities rather than application-name branches.

Dependencies:
    - Python standard library.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    REPOSITORY_ROOT
    / "docs"
    / "release_contracts"
    / "felix_swarm_contract.v1.json"
)


class ReleaseOrchestrationContractTests(unittest.TestCase):
    """Protect candidate identity while forbidding app-specific execution."""

    def setUp(self) -> None:
        """Load the public Felix contract before each test.

        Returns:
            Nothing.
        """

        self.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.site_profile = json.loads(
            (REPOSITORY_ROOT / "site-configs" / "felix.json").read_text(
                encoding="utf-8"
            )
        )

    def test_declared_felix_identity_and_legacy_host_boundary(self) -> None:
        """Keep the intentional Felix defaults and legacy host boundary.

        Returns:
            Nothing.
        """

        candidate = self.contract["candidate"]
        boundary = self.contract["deploymentBoundary"]
        protected = self.contract["legacyProtection"]

        self.assertEqual(candidate["webOrigin"], "https://felix-app.fe-wi.com")
        self.assertEqual(candidate["apiOrigin"], "https://api.felix-app.fe-wi.com")
        self.assertEqual(candidate["realm"], "felix")
        self.assertEqual(candidate["frontendClientId"], "felix-frontend")
        self.assertEqual(candidate["backendAudience"], "felix-backend")
        self.assertEqual(
            candidate["applicationRealmRoles"],
            ["user", "admin"],
        )
        self.assertEqual(
            candidate["bootstrapTestUsernames"],
            ["user", "admin"],
        )
        self.assertIs(candidate["bootstrapTestUsersDefaultEnabled"], True)
        self.assertEqual(boundary["candidateStackName"], "felix")
        self.assertNotEqual(boundary["candidateHost"], boundary["legacyHost"])
        self.assertNotIn(candidate["realm"], protected["protectedRealms"])

    def test_runtime_keycloak_is_existing_swarm_deployment(self) -> None:
        """Keep local-development Keycloak out of production dependencies.

        Returns:
            Nothing.
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

    def test_full_stack_and_cutover_boundaries_are_explicit(self) -> None:
        """Require WebApp/API services and explicit legacy forwarding approval.

        Returns:
            Nothing.
        """

        services = self.contract["stackServices"]
        boundary = self.contract["deploymentBoundary"]
        configuration = self.contract["configurationInput"]

        self.assertEqual(set(services["required"]), {"web", "api", "redis"})
        self.assertEqual(services["optional"], ["pgadmin"])
        self.assertEqual(configuration["wizardGenerated"], ".env")
        self.assertEqual(configuration["forbiddenRequiredInput"], "prod.env")
        self.assertIs(boundary["legacyForwardingRequiresCutoverApproval"], True)
        self.assertIs(boundary["mutableImageTagsAllowed"], False)

    def test_public_contract_cannot_drift_from_site_profile(self) -> None:
        """Keep duplicate evidence identity bound to executable profile data.

        Returns:
            Nothing.
        """

        candidate = self.contract["candidate"]
        routing = self.site_profile["routing"]
        auth = self.site_profile["auth"]
        boundary = self.contract["deploymentBoundary"]

        self.assertEqual(candidate["webOrigin"], routing["webBaseUrl"])
        self.assertEqual(candidate["apiOrigin"], routing["apiBaseUrl"])
        self.assertEqual(candidate["issuerUrl"], auth["issuerUrl"])
        self.assertEqual(candidate["realm"], auth["realm"])
        self.assertEqual(
            candidate["frontendClientId"],
            auth["frontendClientId"],
        )
        self.assertEqual(candidate["backendAudience"], auth["audience"])
        self.assertEqual(
            candidate["applicationRealmRoles"],
            [role["name"] for role in auth["realmRoles"]],
        )
        self.assertEqual(
            candidate["bootstrapTestUsersDefaultEnabled"],
            auth["bootstrapTestUsersEnabled"],
        )
        self.assertEqual(
            candidate["bootstrapTestUsernames"],
            [user["username"] for user in auth["bootstrapTestUsers"]],
        )
        self.assertEqual(
            candidate["backendServiceAccountClientRoles"],
            auth["serviceAccountClientRoles"],
        )
        self.assertEqual(
            boundary["candidateStackName"],
            self.site_profile["stack"]["name"],
        )
        self.assertEqual(
            set(self.contract["legacyProtection"]["protectedRealms"]),
            set(auth["protectedIdentity"]["realms"]),
        )
        self.assertEqual(
            set(self.contract["legacyProtection"]["protectedClientIds"]),
            set(auth["protectedIdentity"]["clientIds"]),
        )

    def test_execution_sources_contain_no_felix_identity(self) -> None:
        """Reject hidden Felix branches in every shared production adapter.

        App-specific values belong in ``site-configs/felix.json`` and public
        documentation, not in setup, rendering, secrets, Keycloak, deployment,
        health, logs, or rollback code.

        Returns:
            Nothing.
        """

        shared_sources = (
            "quick-start.sh",
            "scripts/build-site-stack.sh",
            "scripts/validate-site.sh",
            "scripts/site_profile.py",
            "scripts/executable_profile.py",
            "scripts/executable_profile_support.py",
            "scripts/executable_profile_config_validation.py",
            "scripts/executable_profile_keycloak_validation.py",
            "scripts/executable_profile_deployment_validation.py",
            "scripts/executable_profile_environment.py",
            "scripts/executable_profile_runtime.py",
            "scripts/executable_stack_renderer.py",
            "scripts/keycloak_profile_bootstrap.py",
            "scripts/keycloak_profile_bootstrap_cli.py",
            "scripts/keycloak_profile_application_access.py",
            "scripts/keycloak_profile_cli.py",
            "scripts/keycloak_profile_client.py",
            "scripts/keycloak_profile_realm_role_scope.py",
            "scripts/keycloak_profile_reconciliation.py",
            "scripts/keycloak_profile_roles.py",
            "scripts/keycloak_profile_secret_bridge.py",
            "scripts/keycloak_profile_secret_viewer.py",
            "scripts/keycloak_profile_verification.py",
            "setup/setup-wizard.sh",
            "setup/modules/site_helpers.sh",
            "setup/modules/deployment-profile-prompts.sh",
            "setup/modules/deployment-profile-routing.sh",
            "setup/modules/deployment-profile-services.sh",
            "setup/modules/deployment-profile-inputs.sh",
            "setup/modules/legacy-profile-environment.sh",
            "setup/modules/executable-profile-wizard.sh",
            "setup/modules/deployment-setup-actions.sh",
            "setup/modules/config-builder.sh",
            "setup/modules/keycloak-bootstrap.sh",
            "setup/modules/docker-secrets-menu.sh",
            "setup/modules/menu_handlers.sh",
            "setup/modules/deploy-stack.sh",
        )
        for relative_path in shared_sources:
            content = (REPOSITORY_ROOT / relative_path).read_text(
                encoding="utf-8"
            )
            for forbidden_identity in (
                "felix",
                "secure_messaging",
                "secure-messaging",
            ):
                self.assertNotIn(
                    forbidden_identity,
                    content.lower(),
                    relative_path,
                )

    def test_obsolete_app_specific_adapters_are_absent(self) -> None:
        """Prevent reintroduction of the removed production detour.

        Returns:
            Nothing.
        """

        obsolete_paths = (
            "scripts/felix_deploy.py",
            "scripts/felix_site_profile.py",
            "scripts/felix_stack_renderer.py",
            "scripts/felix_release",
            "setup/modules/felix-production-keycloak.sh",
            "setup/modules/felix-release.sh",
            "setup/modules/felix-setup-wizard.sh",
            "setup/modules/felix-web-setup.sh",
        )
        for relative_path in obsolete_paths:
            path = REPOSITORY_ROOT / relative_path
            if path.is_dir():
                self.assertFalse(any(path.rglob("*")), relative_path)
            else:
                self.assertFalse(path.exists(), relative_path)

    def test_setup_collects_once_then_routes_only_to_adapters(self) -> None:
        """Require one dialog engine before renderer and auth adapters.

        Returns:
            Nothing.
        """

        setup = (REPOSITORY_ROOT / "setup" / "setup-wizard.sh").read_text(
            encoding="utf-8"
        )
        build = (
            REPOSITORY_ROOT / "scripts" / "build-site-stack.sh"
        ).read_text(encoding="utf-8")
        menu = (
            REPOSITORY_ROOT / "setup" / "modules" / "menu_handlers.sh"
        ).read_text(encoding="utf-8")
        quick_start = (REPOSITORY_ROOT / "quick-start.sh").read_text(
            encoding="utf-8"
        )
        executable_setup = (
            REPOSITORY_ROOT
            / "setup"
            / "modules"
            / "executable-profile-wizard.sh"
        ).read_text(encoding="utf-8")
        inputs = (
            REPOSITORY_ROOT
            / "setup"
            / "modules"
            / "deployment-profile-inputs.sh"
        ).read_text(encoding="utf-8")
        routing = (
            REPOSITORY_ROOT
            / "setup"
            / "modules"
            / "deployment-profile-routing.sh"
        ).read_text(encoding="utf-8")
        prompts = (
            REPOSITORY_ROOT
            / "setup"
            / "modules"
            / "deployment-profile-prompts.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('APP_RENDERER_TYPE:-generic}" = "executable"', setup)
        coordinator = setup[setup.index("run_setup_wizard()") :]
        self.assertLess(
            coordinator.index("collect_deployment_configuration"),
            coordinator.index("write_selected_profile_environment"),
        )
        self.assertNotIn("run_executable_profile_setup", setup)
        self.assertIn('"$(_selected_renderer_type)" = "executable"', build)
        self.assertIn("scripts/site_profile.py", build)
        self.assertIn("profile_supports_keycloak_bootstrap", menu)
        self.assertIn("run_profile_keycloak_bootstrap", menu)
        self.assertIn("rollback_stack_services", menu)
        self.assertIn("_deploy_configured_stack", menu)
        self.assertIn("_check_configured_stack_health", menu)
        self.assertNotIn(
            'deploy_stack "$STACK_NAME" "$stack_file"',
            menu,
        )
        self.assertIn(
            'source "${PROJECT_ROOT}/setup/modules/deployment-setup-actions.sh"',
            quick_start,
        )
        self.assertIn(
            'source "${PROJECT_ROOT}/setup/modules/user-prompts.sh"',
            quick_start,
        )
        self.assertNotIn("read -", executable_setup)
        self.assertNotIn("_profile_collect_", executable_setup)
        self.assertIn("prompt_deployment_choice", inputs)
        self.assertIn("prompt_traefik_network", routing)
        self.assertIn("prompt_deployment_choice()", prompts)


if __name__ == "__main__":
    unittest.main()
