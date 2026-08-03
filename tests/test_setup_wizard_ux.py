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
import tempfile
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
MEMORY_POLICY_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "deployment-memory-policy.sh"
)
FIELD_HELP_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "deployment-field-help.sh"
)
ENVIRONMENT_FORMAT_MODULE = (
    REPOSITORY_ROOT
    / "setup"
    / "modules"
    / "deployment-environment-format.sh"
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
IMAGE_ACTIONS = (
    REPOSITORY_ROOT / "setup" / "modules" / "menu-image-actions.sh"
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

    def test_configuration_method_is_selected_after_the_site_profile(
        self,
    ) -> None:
        """Offer guided and file-driven setup only after profile selection.

        Returns:
            Nothing.
        """

        source = SETUP_WIZARD.read_text(encoding="utf-8")
        coordinator = source[source.index("run_setup_wizard()") :]

        self.assertLess(
            coordinator.index("show_selected_deployment_profile"),
            coordinator.index("select_setup_mode"),
        )
        self.assertIn("Guided setup questions (recommended)", source)
        self.assertIn("Edit a generated, commented .env file", source)
        self.assertIn("format_deployment_environment_file", source)
        self.assertIn("deployment-environment-format.sh", source)
        self.assertLess(
            coordinator.index("write_selected_profile_environment"),
            coordinator.index("render_selected_profile_stack"),
        )

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
            "KEYCLOAK_REALM_ENABLED",
            "KEYCLOAK_REGISTRATION_ALLOWED",
            "KEYCLOAK_RESET_PASSWORD_ALLOWED",
            "KEYCLOAK_REMEMBER_ME",
            "KEYCLOAK_VERIFY_EMAIL",
            "KEYCLOAK_LOGIN_WITH_EMAIL_ALLOWED",
            "KEYCLOAK_LOGIN_THEME",
            "KEYCLOAK_ACCOUNT_THEME",
            "KEYCLOAK_ADMIN_THEME",
            "KEYCLOAK_EMAIL_THEME",
            "KEYCLOAK_INTERNATIONALIZATION_ENABLED",
            "KEYCLOAK_SUPPORTED_LOCALES",
            "KEYCLOAK_DEFAULT_LOCALE",
            "KEYCLOAK_EMAIL_SENDER_ENABLED",
            "KEYCLOAK_SMTP_FROM",
            "KEYCLOAK_SMTP_FROM_DISPLAY_NAME",
            "KEYCLOAK_SMTP_REPLY_TO",
            "KEYCLOAK_SMTP_REPLY_TO_DISPLAY_NAME",
            "KEYCLOAK_SMTP_ENVELOPE_FROM",
            "KEYCLOAK_SMTP_HOST",
            "KEYCLOAK_SMTP_PORT",
            "KEYCLOAK_SMTP_STARTTLS",
            "KEYCLOAK_SMTP_SSL",
            "KEYCLOAK_SMTP_AUTH",
            "KEYCLOAK_SMTP_USERNAME",
            "KEYCLOAK_BOOTSTRAP_TEST_USERS_ENABLED",
            "KEYCLOAK_AUDIENCE",
            "KEYCLOAK_FRONTEND_CLIENT_ID",
            "KEYCLOAK_BACKEND_CLIENT_ID",
        )

        for key in keys:
            self.assertIn(f"_deployment_existing_value {key}", inputs)
            self.assertIn(key, adapter)
        self.assertIn('target+=(--set "${key}=${!key:-}")', adapter)
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
        field_help = FIELD_HELP_MODULE.read_text(encoding="utf-8")
        inputs = INPUTS_MODULE.read_text(encoding="utf-8")
        services = SERVICES_MODULE.read_text(encoding="utf-8")
        guide = "https://wiki.fe-wi.com/en/deployment/create-subdomain"

        self.assertIn(f'PUBLIC_DOMAIN_CREATE_INFO_URL="{guide}"', field_help)
        self.assertIn("deployment-field-help.sh", prompts)
        self.assertIn('if [ "$validation_kind" = "domain" ]', prompts)
        self.assertIn("API domain (e.g. api.example.com)", inputs)
        self.assertIn("WebApp domain (e.g. app.example.com)", inputs)
        self.assertIn("pgAdmin domain", services)
        self.assertIn("Mongo Express domain", services)

    def test_memory_limits_are_shared_opt_in_profile_defaults(self) -> None:
        """Default every profile to an omitted Docker memory constraint.

        Returns:
            Nothing.
        """

        for path in sorted((REPOSITORY_ROOT / "site-configs").glob("*.json")):
            with self.subTest(profile=path.name):
                profile = json.loads(path.read_text(encoding="utf-8"))
                resources = profile.get("resources", {})
                self.assertEqual(
                    resources.get("defaultMemoryLimit"),
                    "unlimited",
                )
                if profile.get("services", {}).get("web") is True:
                    self.assertEqual(
                        profile["web"]["resources"]["defaultMemoryLimit"],
                        "unlimited",
                    )

    def test_memory_prompt_documents_units_and_reset_values(self) -> None:
        """Explain byte units and support unlimited reset aliases centrally.

        Returns:
            Nothing.
        """

        prompts = PROMPTS_MODULE.read_text(encoding="utf-8")
        policy = MEMORY_POLICY_MODULE.read_text(encoding="utf-8")
        field_help = FIELD_HELP_MODULE.read_text(encoding="utf-8")

        self.assertIn("print_deployment_field_help", prompts)
        self.assertIn("print_deployment_memory_limit_help", field_help)
        self.assertIn("bytes, not bits", policy)
        self.assertIn("K/M/G/T (1024-based)", policy)
        self.assertIn("enter unlimited/0", policy)
        self.assertIn("###MEMORY_LIMIT_START###", policy)

    def test_public_env_comments_and_prompts_share_field_help(self) -> None:
        """Use one guidance catalog for terminal and editable-file setup.

        Returns:
            Nothing.
        """

        prompts = PROMPTS_MODULE.read_text(encoding="utf-8")
        help_source = FIELD_HELP_MODULE.read_text(encoding="utf-8")
        format_source = ENVIRONMENT_FORMAT_MODULE.read_text(encoding="utf-8")

        self.assertIn("print_deployment_field_help", prompts)
        self.assertIn("deployment_field_help_text", help_source)
        self.assertIn("deployment_field_help_id", help_source)
        self.assertIn("deployment_field_help_text", format_source)
        self.assertIn("format_deployment_environment_file", format_source)
        self.assertIn("Canonical section order", format_source)
        self.assertIn("Profile-owned identity value", help_source)
        self.assertIn("Do not add passwords", SETUP_WIZARD.read_text(encoding="utf-8"))

    @unittest.skipIf(
        sys.platform.startswith("win") or shutil.which("bash") is None,
        "Native Bash environment-format test runs on Linux hosts.",
    )
    def test_generated_public_environment_is_structured_and_value_safe(
        self,
    ) -> None:
        """Group assignments and consolidate help without evaluating values.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary:
            environment_file = Path(temporary) / ".env"
            source_environment = (
                "# Generated by the shared site-config setup wizard.\n"
                "# Deployment profile: felix\n"
                "PROFILE_SCHEMA_VERSION=5.0\n"
                "DEPLOYMENT_PROFILE_ID=felix\n"
                "APP_ID=felix\n"
                "STACK_NAME=felix\n"
                "API_BASE_URL=https://api.example.com\n"
                "DOMAIN=api.example.com\n"
                "AUTH_PROVIDER=keycloak\n"
                "KEYCLOAK_REALM=felix\n"
                "KEYCLOAK_REALM_DISPLAY_NAME=Felix\n"
                "KEYCLOAK_REALM_ENABLED=true\n"
                "DB_TYPE=postgresql\n"
                "DB_MODE=local\n"
                "POSTGRES_HOST=postgres\n"
                "POSTGRES_PASSWORD_FILE=/run/secrets/FELIX_DB_PASSWORD\n"
                "IMAGE_NAME=example/backend\n"
                "MEMORY_LIMIT=unlimited\n"
                "UNMAPPED_PROFILE_VALUE=$(printf should-not-run)\n"
            )
            environment_file.write_text(
                source_environment,
                encoding="utf-8",
            )
            script = f"""
source {shlex_quote(ENVIRONMENT_FORMAT_MODULE)}
format_deployment_environment_file {shlex_quote(environment_file)}
"""
            completed = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )
            annotated = environment_file.read_text(encoding="utf-8")
            environment_mode = environment_file.stat().st_mode & 0o777

        self.assertEqual(completed.returncode, 0, completed.stderr)
        titles = (
            "# Deployment identity",
            "# Docker Swarm topology",
            "# Routing and browser access",
            "# Authentication",
            "# Database",
            "# Backend service",
            "# Docker secret references",
            "# Additional profile settings",
        )
        positions = [annotated.index(title) for title in titles]
        self.assertEqual(positions, sorted(positions))
        self.assertGreaterEqual(
            annotated.count("# =============================================================================="),
            len(titles) * 2,
        )
        identity_block = annotated[
            positions[0] : positions[1]
        ]
        self.assertEqual(
            identity_block.count("Profile-owned identity value"),
            1,
        )
        self.assertIn("K/M/G/T (1024-based)", annotated)
        self.assertIn("Human-readable realm name", annotated)
        self.assertIn("Docker secret mount path only", annotated)
        self.assertIn("Site-profile deployment setting", annotated)
        self.assertIn(
            "UNMAPPED_PROFILE_VALUE=$(printf should-not-run)",
            annotated,
        )
        self.assertIn("Public configuration only", annotated)
        original_assignments = sorted(
            line
            for line in source_environment.splitlines()
            if line and not line.startswith("#")
        )
        formatted_assignments = sorted(
            line
            for line in annotated.splitlines()
            if line and not line.startswith("#")
        )
        self.assertEqual(formatted_assignments, original_assignments)
        self.assertEqual(environment_mode, 0o600)

    @unittest.skipIf(
        sys.platform.startswith("win") or shutil.which("bash") is None,
        "Native Bash memory-prompt smoke test runs on Linux hosts.",
    )
    def test_memory_prompt_normalizes_reset_aliases(self) -> None:
        """Normalize Enter, zero, and unlimited while retaining explicit units.

        Returns:
            Nothing.
        """

        script = (
            f"source {shlex_quote(PROMPTS_MODULE)}; "
            "prompt_deployment_value first 'Backend memory limit' 512M memory; "
            "prompt_deployment_value second 'WebApp memory limit' 128M memory; "
            "prompt_deployment_value third 'Backend memory limit' unlimited memory; "
            "prompt_deployment_value fourth 'WebApp memory limit' unlimited memory; "
            'printf "RESULT=%s|%s|%s|%s\\n" '
            '"$first" "$second" "$third" "$fourth"'
        )
        completed = subprocess.run(
            ["bash", "-c", script],
            input="0\nunlimited\n\n2GiB\n",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "RESULT=unlimited|unlimited|unlimited|2GiB",
            completed.stdout,
        )
        self.assertEqual(completed.stdout.count("bytes, not bits"), 4)

    @unittest.skipIf(
        sys.platform.startswith("win") or shutil.which("bash") is None,
        "Native Bash template-policy smoke test runs on Linux hosts.",
    )
    def test_unlimited_template_policy_omits_resource_block(self) -> None:
        """Remove marked Compose limits and retain explicitly bounded limits.

        Returns:
            Nothing.
        """

        template = """before
###MEMORY_LIMIT_START###
resources:
  limits:
    memory: ${MEMORY_LIMIT}
###MEMORY_LIMIT_END###
after
"""
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "stack.yml"
            target.write_text(template, encoding="utf-8")
            unlimited = subprocess.run(
                [
                    "bash",
                    "-c",
                    (
                        f"source {shlex_quote(MEMORY_POLICY_MODULE)}; "
                        "apply_deployment_memory_limit_template "
                        f"{shlex_quote(target)} unlimited"
                    ),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(unlimited.returncode, 0, unlimited.stderr)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "before\nafter\n",
            )

            target.write_text(template, encoding="utf-8")
            explicit = subprocess.run(
                [
                    "bash",
                    "-c",
                    (
                        f"source {shlex_quote(MEMORY_POLICY_MODULE)}; "
                        "apply_deployment_memory_limit_template "
                        f"{shlex_quote(target)} 512M"
                    ),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            rendered = target.read_text(encoding="utf-8")
            self.assertEqual(explicit.returncode, 0, explicit.stderr)
            self.assertIn("memory: ${MEMORY_LIMIT}", rendered)
            self.assertNotIn("###MEMORY_LIMIT", rendered)

    def test_web_domain_precedes_and_can_default_api_domain(self) -> None:
        """Collect a WebApp identity before its conventionally derived API.

        Explicit persisted or profile API defaults remain authoritative; the
        derivation is used only when both sources are empty.

        Returns:
            Nothing.
        """

        inputs = INPUTS_MODULE.read_text(encoding="utf-8")
        public_collector = inputs[
            inputs.index("_collect_public_domains()") : inputs.index(
                "# _collect_stack_and_domains"
            )
        ]

        self.assertLess(
            public_collector.index("WebApp domain"),
            public_collector.index("API domain"),
        )
        self.assertIn(
            '[ -z "$default_domain" ] && [ -n "$WEB_DOMAIN" ]',
            public_collector,
        )
        self.assertIn(
            'default_domain="api.${WEB_DOMAIN}"',
            public_collector,
        )

    @unittest.skipIf(
        sys.platform.startswith("win") or shutil.which("bash") is None,
        "Native Bash domain-default smoke test runs on Linux hosts.",
    )
    def test_web_answer_drives_missing_api_default(self) -> None:
        """Derive the API prompt default from the entered WebApp domain.

        Returns:
            Nothing.
        """

        script = f"""
source {shlex_quote(PROMPTS_MODULE)}
source {shlex_quote(INPUTS_MODULE)}
PROJECT_ROOT=/tmp/nonexistent-deployment-profile-test
APP_REQUIRES_WEB=true
APP_ROUTING_WEB_DOMAIN=
APP_ROUTING_DOMAIN=
declare -a calls=()
prompt_deployment_value() {{
    local target_name="$1"
    local default_value="$3"
    calls+=("${{target_name}}:${{default_value}}")
    if [ "$target_name" = "WEB_DOMAIN" ]; then
        printf -v "$target_name" '%s' 'felix-app.fe-wi.com'
    else
        printf -v "$target_name" '%s' "$default_value"
    fi
}}
_collect_public_domains
printf 'CALLS=%s\n' "$(IFS=,; echo "${{calls[*]}}")"
printf 'DOMAINS=%s|%s\n' "$WEB_DOMAIN" "$DOMAIN"
"""
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            "CALLS=WEB_DOMAIN:,DOMAIN:api.felix-app.fe-wi.com",
            completed.stdout,
        )
        self.assertIn(
            "DOMAINS=felix-app.fe-wi.com|api.felix-app.fe-wi.com",
            completed.stdout,
        )

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

    def test_management_changes_remain_profile_driven(self) -> None:
        """Keep targeted and full management paths out of renderer branches.

        Returns:
            Nothing.
        """

        menu_source = MENU_HANDLERS.read_text(encoding="utf-8")
        image_source = IMAGE_ACTIONS.read_text(encoding="utf-8")

        self.assertNotIn("profile_uses_executable_renderer", menu_source)
        self.assertNotIn("docker service update --image", menu_source)
        self.assertNotIn("docker service scale", menu_source)
        self.assertIn("manage_service_images", menu_source)
        self.assertIn("_run_shared_reconfiguration", menu_source)
        self.assertIn("_managed_release_image_records", image_source)
        self.assertNotIn("felix", image_source.lower())

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
