"""
Module: test_setup_wizard_ux.py

Description:
    Protects the single site-config-driven setup dialogue from renderer-based
    divergence. The tests focus on stable architectural contracts and run one
    Bash prompt smoke test on native Linux hosts.

Dependencies:
    - Python standard library.
    - Bash on non-Windows verification hosts for the optional prompt smoke test.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SETUP_WIZARD = REPOSITORY_ROOT / "setup" / "setup-wizard.sh"
INPUTS_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "deployment-profile-inputs.sh"
)
ROUTING_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "deployment-profile-routing.sh"
)
SERVICES_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "deployment-profile-services.sh"
)
PROMPTS_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "deployment-profile-prompts.sh"
)
EXECUTABLE_ADAPTER = (
    REPOSITORY_ROOT / "setup" / "modules" / "executable-profile-wizard.sh"
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


class SetupWizardUxTests(unittest.TestCase):
    """Verify one numbered dialogue feeds every renderer adapter."""

    def test_main_menu_numbers_secret_management_before_environment_restore(
        self,
    ) -> None:
        """Assign and display secret management before environment restore.

        Returns:
            Nothing.
        """

        source = MENU_HANDLERS.read_text(encoding="utf-8")
        allocation = source[
            source.index("while true; do") : source.index(
                'local MENU_SETUP_AUTH=""'
            )
        ]
        display = source[
            source.index('echo "Setup:"') : source.index('echo "Deployment:"')
        ]

        self.assertLess(
            allocation.index("MENU_SETUP_SECRETS=$MENU_NEXT"),
            allocation.index("local MENU_RESTORE_ENV=$MENU_NEXT"),
        )
        self.assertLess(
            display.index("Manage Docker secrets"),
            display.index("Quick restore from saved .env"),
        )

    def test_renderer_dispatch_occurs_after_shared_collection(self) -> None:
        """Require collection before persistence and rendering dispatch.

        Returns:
            Nothing.
        """

        source = SETUP_WIZARD.read_text(encoding="utf-8")
        coordinator = source[source.index("run_setup_wizard()") :]

        self.assertLess(
            coordinator.index("collect_deployment_configuration"),
            coordinator.index("write_selected_profile_environment"),
        )
        self.assertLess(
            coordinator.index("write_selected_profile_environment"),
            coordinator.index("render_selected_profile_stack"),
        )
        self.assertNotIn("run_executable_profile_setup", coordinator)

    def test_executable_adapter_has_no_operator_dialogue(self) -> None:
        """Keep schema-5 code behind the shared input boundary.

        Returns:
            Nothing.
        """

        source = EXECUTABLE_ADAPTER.read_text(encoding="utf-8")

        self.assertNotIn("read -", source)
        self.assertNotIn("_profile_prompt_", source)
        self.assertNotIn("_profile_collect_", source)
        self.assertNotIn("Next action", source)

    def test_root_environment_rehydrates_its_declared_profile(self) -> None:
        """Prevent restored environments from retaining stale capabilities.

        Returns:
            Nothing.
        """

        source = SITE_HELPERS.read_text(encoding="utf-8")
        loader = source[source.index("load_root_env()") :]

        self.assertIn('load_app_config "$project_root" "$profile_id"', loader)
        self.assertIn("Deployment profile is missing:", loader)

    def test_keycloak_choices_survive_shared_wizard_reruns(self) -> None:
        """Carry persisted identity through the generic executable adapter.

        Returns:
            Nothing.
        """

        inputs = INPUTS_MODULE.read_text(encoding="utf-8")
        adapter = EXECUTABLE_ADAPTER.read_text(encoding="utf-8")
        bootstrap = KEYCLOAK_BOOTSTRAP.read_text(encoding="utf-8")
        keys = (
            "KEYCLOAK_REALM",
            "KEYCLOAK_REALM_DISPLAY_NAME",
            "KEYCLOAK_AUDIENCE",
            "KEYCLOAK_FRONTEND_CLIENT_ID",
            "KEYCLOAK_BACKEND_CLIENT_ID",
        )

        for key in keys:
            self.assertIn(f"_deployment_existing_value {key}", inputs)
            self.assertIn(f'--set "{key}=${{{key}}}"', adapter)
        self.assertIn("saved to root .env", bootstrap)
        self.assertIn("rebuild swarm-stack.yml", bootstrap)
        self.assertIn("credential trust anchor", bootstrap)

    def test_common_sections_are_capability_driven(self) -> None:
        """Require shared service/routing prompts without app-name branches.

        Returns:
            Nothing.
        """

        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (INPUTS_MODULE, ROUTING_MODULE, SERVICES_MODULE)
        )
        required_tokens = (
            "Docker stack name",
            "Database mode",
            "Proxy type",
            "SSL mode",
            "prompt_traefik_network",
            "Traefik provider constraint label",
            "${label} image repository",
            "${label} image version",
            "${label} replicas",
            "${label} memory limit",
            "APP_REQUIRES_WEB",
            "APP_IS_INTERNAL",
            "APP_ADMIN_UI_TYPE",
            "APP_REDIRECTOR_ENABLED",
        )

        for token in required_tokens:
            self.assertIn(token, source)
        self.assertNotIn("felix", source.lower())
        self.assertNotIn("secure_messaging", source.lower())

    def test_public_domain_prompts_share_subdomain_creation_help(self) -> None:
        """Add the Wiki guide to every validated public-domain question.

        The prompt primitive must preserve existing example parentheses and
        decorate plain service labels without requiring app-specific branches.

        Returns:
            Nothing.
        """

        prompts = PROMPTS_MODULE.read_text(encoding="utf-8")
        inputs = INPUTS_MODULE.read_text(encoding="utf-8")
        services = SERVICES_MODULE.read_text(encoding="utf-8")
        guide = "https://wiki.fe-wi.com/en/deployment/create-subdomain"

        self.assertIn(f'PUBLIC_DOMAIN_CREATE_INFO_URL="{guide}"', prompts)
        self.assertIn('if [ "$validation_kind" = "domain" ]', prompts)
        self.assertIn("API domain (e.g. api.example.com)", inputs)
        self.assertIn("WebApp domain (e.g. app.example.com)", inputs)
        self.assertIn("pgAdmin domain", services)
        self.assertIn("Mongo Express domain", services)

    def test_data_root_uses_profile_or_checkout_default(self) -> None:
        """Use an optional profile default and retain an explicit choice.

        Returns:
            Nothing.
        """

        services = SERVICES_MODULE.read_text(encoding="utf-8")
        helpers = SITE_HELPERS.read_text(encoding="utf-8")
        felix = json.loads(
            (REPOSITORY_ROOT / "site-configs" / "felix.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("'.storage.dataRoot'", helpers)
        self.assertIn('"$project_root")', helpers)
        self.assertIn("Host data root", services)
        self.assertIn("_deployment_existing_value DATA_ROOT", services)
        self.assertEqual(
            felix["storage"]["dataRoot"],
            "/swarm/prod/felix",
        )

    def test_management_changes_reuse_the_shared_dialogue(self) -> None:
        """Keep image, replica, and admin settings out of renderer branches.

        Returns:
            Nothing.
        """

        source = MENU_HANDLERS.read_text(encoding="utf-8")

        self.assertNotIn("profile_uses_executable_renderer", source)
        self.assertNotIn("docker service update --image", source)
        self.assertNotIn("docker service scale", source)
        self.assertIn("_run_shared_reconfiguration", source)

    def test_profile_data_expresses_real_service_differences(self) -> None:
        """Verify Felix and Secure Messaging differ through profile data.

        Returns:
            Nothing.
        """

        felix = json.loads(
            (REPOSITORY_ROOT / "site-configs" / "felix.json").read_text(
                encoding="utf-8"
            )
        )
        internal = json.loads(
            (
                REPOSITORY_ROOT
                / "site-configs"
                / "secure_messaging.json"
            ).read_text(encoding="utf-8")
        )

        self.assertIs(felix["services"]["web"], True)
        self.assertEqual(felix["exposure"]["type"], "public")
        self.assertEqual(felix["database"]["allowedModes"], ["local", "external"])
        self.assertEqual(internal["exposure"]["type"], "internal")
        self.assertIs(internal["exposure"]["traefik"], False)
        self.assertEqual(internal["database"]["type"], "none")
        self.assertEqual(internal["stack"]["role"], "internal-api")

    @unittest.skipIf(
        sys.platform.startswith("win") or shutil.which("bash") is None,
        "Native Bash prompt smoke test runs on Linux verification hosts.",
    )
    def test_numbered_choice_reprompts_then_accepts_enter_default(self) -> None:
        """Reject an invalid number and map Enter to the stable default.

        Returns:
            Nothing.
        """

        script = (
            f"source {shlex_quote(PROMPTS_MODULE)}; "
            "prompt_deployment_choice result 'Proxy type' traefik "
            "'traefik|Traefik' 'none|None'; "
            'printf "RESULT=%s\\n" "$result"'
        )
        completed = subprocess.run(
            ["bash", "-c", script],
            input="9\n\n",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("1) Traefik", completed.stdout)
        self.assertIn("2) None", completed.stdout)
        self.assertIn("Invalid choice: '9'", completed.stdout)
        self.assertIn("RESULT=traefik", completed.stdout)

    @unittest.skipIf(
        sys.platform.startswith("win") or shutil.which("bash") is None,
        "Native Bash prompt-label test runs on Linux verification hosts.",
    )
    def test_public_domain_label_places_help_inside_existing_parentheses(
        self,
    ) -> None:
        """Render exact API and service-domain labels without duplicate links.

        Returns:
            Nothing.
        """

        script = (
            f"source {shlex_quote(PROMPTS_MODULE)}; "
            "_deployment_public_domain_prompt_label "
            "'API domain (e.g. api.example.com)'; printf '\\n'; "
            "_deployment_public_domain_prompt_label 'pgAdmin domain'"
        )
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )
        guide = "https://wiki.fe-wi.com/en/deployment/create-subdomain"

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.splitlines(),
            [
                f"API domain (e.g. api.example.com, create-info: {guide})",
                f"pgAdmin domain (create-info: {guide})",
            ],
        )


def shlex_quote(path: Path) -> str:
    """Quote one path for the Linux-only Bash smoke test.

    Args:
        path: Filesystem path to quote.

    Returns:
        Single-quoted shell word with embedded quotes escaped.
    """

    return "'" + str(path).replace("'", "'\"'\"'") + "'"


if __name__ == "__main__":
    unittest.main()
