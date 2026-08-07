"""
Module: test_service_image_management.py

Description:
    Protects profile persistence, all-service overview rendering, shared
    registry-backed image selection, and the targeted operations-menu image
    update workflow. Native Bash tests use isolated temporary files and stub
    registry/runtime functions, so they never contact Docker or Swarm.

Dependencies:
    - Python standard library.
    - Bash on non-Windows verification hosts for integration checks.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from executable_profile_environment import load_config_defaults  # noqa: E402
from executable_profile_support import ExecutableProfileError  # noqa: E402


SETUP_WIZARD = REPOSITORY_ROOT / "setup" / "setup-wizard.sh"
MENU_HANDLERS = REPOSITORY_ROOT / "setup" / "modules" / "menu_handlers.sh"
MENU_OVERVIEW = REPOSITORY_ROOT / "setup" / "modules" / "menu-overview.sh"
MENU_FORMATTING = (
    REPOSITORY_ROOT / "setup" / "modules" / "menu_formatting.sh"
)
MENU_SHORTCUTS = (
    REPOSITORY_ROOT / "setup" / "modules" / "menu-shortcuts.sh"
)
MENU_RUNTIME_ACTIONS = (
    REPOSITORY_ROOT / "setup" / "modules" / "menu-runtime-actions.sh"
)
IMAGE_ACTIONS = (
    REPOSITORY_ROOT / "setup" / "modules" / "menu-image-actions.sh"
)
IMAGE_TRANSACTION = (
    REPOSITORY_ROOT / "setup" / "modules" / "menu-image-transaction.sh"
)
IMAGE_AUDIT = (
    REPOSITORY_ROOT / "setup" / "modules" / "menu-image-audit.sh"
)
INFRASTRUCTURE_IMAGES = (
    REPOSITORY_ROOT / "setup" / "modules" / "menu-infrastructure-images.sh"
)
INFRASTRUCTURE_SAFETY = (
    REPOSITORY_ROOT / "setup" / "modules" / "infrastructure-image-safety.sh"
)
INFRASTRUCTURE_ADAPTER = (
    REPOSITORY_ROOT / "setup" / "modules" / "menu-image-audit-profile.sh"
)
SEMANTIC_VERSION = (
    REPOSITORY_ROOT / "setup" / "modules" / "semantic-version.sh"
)
PROFILE_PROMPTS = (
    REPOSITORY_ROOT / "setup" / "modules" / "deployment-profile-prompts.sh"
)
NATIVE_BASH_AVAILABLE = (
    not sys.platform.startswith("win") and shutil.which("bash") is not None
)


class ServiceImageManagementStaticTests(unittest.TestCase):
    """Verify generic routing and persisted-profile contracts on every host."""

    def test_infrastructure_updates_are_track_locked_and_transactional(self) -> None:
        """Protect generic inventory, backup, ignore, and deploy boundaries.

        Returns:
            Nothing.
        """

        menu = INFRASTRUCTURE_IMAGES.read_text(encoding="utf-8")
        safety = INFRASTRUCTURE_SAFETY.read_text(encoding="utf-8")
        adapter = INFRASTRUCTURE_ADAPTER.read_text(encoding="utf-8")
        handlers = MENU_HANDLERS.read_text(encoding="utf-8")

        self.assertIn("Current versions are inferred", menu)
        self.assertIn("PostgreSQL data-safety checkpoint", safety)
        self.assertIn("Ignore this exact target digest", menu)
        self.assertIn("fixable HIGH/CRITICAL", safety)
        self.assertIn("may cross a major version", safety)
        self.assertIn("PostgreSQL|postgres|POSTGRES_IMAGE", adapter)
        self.assertIn("Redis|redis|REDIS_IMAGE", adapter)
        self.assertIn("pgAdmin|pgadmin|PGADMIN_IMAGE", adapter)
        self.assertIn("_apply_profile_environment_update", adapter)
        self.assertIn("menu-infrastructure-images.sh", handlers)

    def test_release_coordination_metadata_is_generic_and_complete(self) -> None:
        """Accept one app-neutral monotonic component catalog.

        Returns:
            Nothing.
        """

        profile = json.loads(
            (REPOSITORY_ROOT / "site-configs" / "felix.json").read_text(
                encoding="utf-8"
            )
        )
        release = profile["release"]

        self.assertEqual(release["stackId"], "felix")
        self.assertEqual(release["versionPolicy"], "monotonic-floor")
        self.assertEqual(release["versionFloor"], "1.0.8")
        self.assertEqual(
            release["components"],
            ["api", "web", "android", "ios"],
        )
        self.assertEqual(profile["database"]["imageTrackTag"], "16-alpine")
        self.assertEqual(profile["services"]["redisImageTrackTag"], "7-alpine")

    def test_release_coordination_rejects_unsafe_or_incomplete_values(
        self,
    ) -> None:
        """Reject invalid floors, policies, duplicates, and service omissions.

        Returns:
            Nothing.
        """

        source_profile = json.loads(
            (REPOSITORY_ROOT / "site-configs" / "felix.json").read_text(
                encoding="utf-8"
            )
        )
        invalid_floor = copy.deepcopy(source_profile)
        invalid_floor["release"]["versionFloor"] = "v1.0.8"
        invalid_policy = copy.deepcopy(source_profile)
        invalid_policy["release"]["versionPolicy"] = "independent"
        duplicate_component = copy.deepcopy(source_profile)
        duplicate_component["release"]["components"].append("web")
        missing_web = copy.deepcopy(source_profile)
        missing_web["release"]["components"].remove("web")
        missing_database_track = copy.deepcopy(source_profile)
        del missing_database_track["database"]["imageTrackTag"]
        cases = (
            (invalid_floor, "release.versionFloor"),
            (invalid_policy, "release.versionPolicy"),
            (duplicate_component, "release.components must contain unique"),
            (missing_web, "release.components omits managed services: web"),
            (
                missing_database_track,
                "database.image and database.imageTrackTag must be declared together",
            ),
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            config_directory = root / "site-configs"
            config_directory.mkdir()
            profile_path = config_directory / "felix.json"
            for invalid, message in cases:
                with self.subTest(expected=message):
                    profile_path.write_text(
                        json.dumps(invalid, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        ExecutableProfileError,
                        message,
                    ):
                        load_config_defaults(root, "felix")

    def test_option_ten_uses_targeted_image_management(self) -> None:
        """Route image changes directly without reopening the setup wizard.

        Returns:
            Nothing.
        """

        source = MENU_HANDLERS.read_text(encoding="utf-8")
        case_start = source.index('case "$choice"')
        image_start = source.index("${MENU_UPDATE_IMAGE})", case_start)
        image_end = source.index("${MENU_SCALE})", image_start)
        image_case = source[image_start:image_end]

        self.assertIn("manage_service_images", image_case)
        self.assertNotIn("_run_shared_reconfiguration", image_case)
        self.assertIn("menu-image-actions.sh", source)

    def test_existing_installation_reuses_persisted_profile(self) -> None:
        """Avoid asking an installed clone to select its profile again.

        Returns:
            Nothing.
        """

        source = SETUP_WIZARD.read_text(encoding="utf-8")
        selector = source[
            source.index("select_setup_profile()") : source.index(
                "# select_setup_mode"
            )
        ]

        self.assertIn("DEPLOYMENT_PROFILE_ID", selector)
        self.assertIn("BACKEND_APP_ID", selector)
        self.assertIn("Deployment profile from .env", selector)
        self.assertIn("show_app_selector", selector)
        self.assertLess(
            selector.index("Deployment profile from .env"),
            selector.index("show_app_selector"),
        )

    def test_overview_discovers_all_stack_services(self) -> None:
        """Use namespace discovery and remove the single-API image summary.

        Returns:
            Nothing.
        """

        overview = MENU_OVERVIEW.read_text(encoding="utf-8")
        quick_start = (REPOSITORY_ROOT / "quick-start.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("com.docker.stack.namespace", overview)
        self.assertIn("{{.Name}}|{{.Replicas}}|{{.Image}}", overview)
        self.assertIn("_print_boxed_service_overview", overview)
        self.assertNotIn("show_plain_deployment_overview", quick_start)
        self.assertNotIn("show_plain_deployment_overview", overview)
        self.assertIn("show_deployment_overview", overview)
        self.assertNotIn(
            'echo "Image:          ${IMAGE_NAME:-not set}',
            quick_start,
        )

    def test_shared_modules_contain_no_application_identity(self) -> None:
        """Keep overview and image management free of Felix branches.

        Returns:
            Nothing.
        """

        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                MENU_OVERVIEW,
                IMAGE_ACTIONS,
                IMAGE_TRANSACTION,
                IMAGE_AUDIT,
                SEMANTIC_VERSION,
            )
        ).lower()

        self.assertNotIn("felix", source)
        self.assertIn("app_requires_web", source)
        self.assertIn("app_primary_service", source)
        self.assertIn("app_release_version_floor", source)
        self.assertIn("registry_stable_tags", source)

    def test_image_action_reuses_shared_deploy_and_health_boundary(self) -> None:
        """Require render, preconfirmed deploy, and health-result handling.

        Returns:
            Nothing.
        """

        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (IMAGE_ACTIONS, IMAGE_TRANSACTION)
        )

        self.assertIn("scripts/build-site-stack.sh", source)
        self.assertIn("_deploy_configured_stack confirmed", source)
        self.assertIn("DEPLOY_CONFIGURED_STACK_MUTATED", source)
        self.assertIn("health-verified", source)
        self.assertNotIn("docker service update --image", source)

    def test_operator_shortcuts_have_stable_cross_repository_meanings(
        self,
    ) -> None:
        """Protect the shared letters from menu-number and feature drift.

        Returns:
            Nothing.
        """

        source = MENU_SHORTCUTS.read_text(encoding="utf-8")
        expected = {
            "audit-images": "a",
            "bootstrap": "b",
            "deploy": "d",
            "logging": "g",
            "health": "h",
            "images": "i",
            "logs": "l",
            "database-admin": "p",
            "refresh": "r",
            "secrets": "s",
            "update": "u",
            "exit": "q",
        }

        for action, key in expected.items():
            with self.subTest(action=action):
                self.assertIn(f'{action}) echo "{key}"', source)

    def test_repository_update_action_uses_warning_color(self) -> None:
        """Highlight the actionable update row as a semantic warning.

        Returns:
            Nothing.
        """

        source = MENU_HANDLERS.read_text(encoding="utf-8")

        self.assertIn(
            'echo "  $(_menu_colorize warning "$(operator_menu_shortcut_key update))',
            source,
        )

    def test_all_shell_status_markers_use_shared_terminal_colors(self) -> None:
        """Color common outcomes centrally without polluting captured output.

        Returns:
            Nothing.
        """

        source = MENU_FORMATTING.read_text(encoding="utf-8")

        self.assertIn("_menu_semantic_level_for_text", source)
        self.assertIn("echo()", source)
        self.assertIn("_menu_colorize_stream", source)
        self.assertIn("*'[ERROR]'*", source)
        self.assertIn("*'[WARN]'*", source)
        self.assertIn("*'[OK]'*", source)
        self.assertIn('[ -t 1 ]', source)
        self.assertIn('${NO_COLOR:-}', source)

    def test_missing_image_scanners_show_official_install_steps(self) -> None:
        """Give operators directly runnable Scout and Trivy recovery steps.

        Returns:
            Nothing.
        """

        source = IMAGE_AUDIT.read_text(encoding="utf-8")

        self.assertIn("docker/scout-cli/main/install.sh", source)
        self.assertIn("aquasecurity.github.io/trivy-repo/deb", source)
        self.assertIn("docker scout version", source)
        self.assertIn("trivy --version", source)
        self.assertIn("https://docs.docker.com/scout/", source)
        self.assertIn("https://trivy.dev/docs/latest/", source)

    def test_deployment_choices_are_registry_backed_not_floor_generated(
        self,
    ) -> None:
        """Keep build policy separate from deployed-image freshness.

        Returns:
            Nothing.
        """

        actions = IMAGE_ACTIONS.read_text(encoding="utf-8")
        overview = MENU_OVERVIEW.read_text(encoding="utf-8")

        self.assertIn("registry_stable_tags", actions)
        self.assertIn("registry_verify_tag", actions)
        self.assertIn("highest published stable version", actions)
        self.assertNotIn("select_semantic_version", actions)
        self.assertNotIn("below the", overview.lower())
        self.assertIn("next minimum", overview)

    def test_quick_runtime_actions_reuse_the_deployment_transaction(
        self,
    ) -> None:
        """Keep logging and database-admin toggles generic and rollback-safe.

        Returns:
            Nothing.
        """

        source = MENU_RUNTIME_ACTIONS.read_text(encoding="utf-8")

        self.assertIn("_apply_profile_environment_update", source)
        self.assertIn("ADVANCED_LOGGING_ENABLED=${target}", source)
        self.assertIn("PGADMIN_ENABLED=${target}", source)
        self.assertIn("PGADMIN_REPLICAS=${replicas}", source)
        self.assertIn("Sensitive HTTP bodies/headers", source)
        self.assertNotIn('LOG_LEVEL=DEBUG', source)


@unittest.skipUnless(
    NATIVE_BASH_AVAILABLE,
    "Service image workflow integration tests require native Bash.",
)
class ServiceImageManagementBashTests(unittest.TestCase):
    """Exercise shared Bash helpers without external runtime effects."""

    def test_boxed_overview_lists_every_managed_service(self) -> None:
        """Render API, WebApp, Redis, PostgreSQL, and pgAdmin together.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(MENU_OVERVIEW)}
_box_rule() {{ echo RULE; }}
_box_line() {{ echo "$1"; }}
_box_line_list() {{ echo " - $1"; }}
_stack_running() {{ return 0; }}
_stack_services_healthy() {{ return 0; }}
_deployed_stack_service_records() {{
    printf '%s\n' \
      'demo_api|1/1|registry/backend:1.0.6' \
      'demo_web|1/1|registry/web:1.0.6' \
      'demo_redis|1/1|redis@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
      'demo_postgres|1/1|postgres@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb' \
      'demo_pgadmin|1/1|pgadmin@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc'
}}
STACK_NAME=demo
DEPLOYMENT_PROFILE_ID=example
PROXY_TYPE=traefik
DB_TYPE=postgresql
DOMAIN=api.example.com
WEB_DOMAIN=app.example.com
KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_PENDING=true
KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_NAMES=test-admin,test-user
show_deployment_overview
"""
        completed = run_bash(script)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        for service in ("api", "web", "redis", "postgres"):
            self.assertIn(f"[OK] {service} (1/1)", completed.stdout)
        self.assertIn("[WARN] pgadmin (1/1)", completed.stdout)
        self.assertIn("management UI active", completed.stdout)
        self.assertIn(
            "Bootstrap users: [WARN] manual cleanup pending: test-admin,test-user",
            completed.stdout,
        )
        self.assertEqual(completed.stdout.count("manual cleanup pending"), 1)
        self.assertIn("API      : api.example.com", completed.stdout)
        self.assertIn("WebApp   : app.example.com", completed.stdout)

    def test_overview_marks_missing_replicas_and_unhealthy_stack_as_error(
        self,
    ) -> None:
        """Use red-severity labels for a stopped or under-replicated service.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(MENU_OVERVIEW)}
_box_rule() {{ echo RULE; }}
_box_line() {{ echo "$1"; }}
_box_line_list() {{ echo " - $1"; }}
_stack_running() {{ return 0; }}
_stack_services_healthy() {{ return 1; }}
_deployed_stack_service_records() {{
    printf '%s\n' 'demo_api|0/1|registry/backend:1.0.6'
}}
STACK_NAME=demo
DEPLOYMENT_PROFILE_ID=example
show_deployment_overview
"""
        completed = run_bash(script)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("[ERROR] unhealthy", completed.stdout)
        self.assertIn("[ERROR] api (0/1)", completed.stdout)

    def test_overview_colors_semantic_statuses_on_interactive_terminals(
        self,
    ) -> None:
        """Retain explicit labels while applying standard ANSI status colors.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(MENU_OVERVIEW)}
_MENU_COLOR_ENABLED=true
printf 'ok=%s\n' "$(_menu_colorize ok '[OK] healthy')"
printf 'warn=%s\n' "$(_menu_colorize warning '[WARN] review')"
printf 'error=%s\n' "$(_menu_colorize error '[ERROR] unhealthy')"
colorized="$(_menu_colorize error '[ERROR] unhealthy')"
printf 'width=%s\n' "$(_calc_display_width "$colorized")"
"""
        completed = run_bash(script)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("\x1b[32m[OK] healthy\x1b[0m", completed.stdout)
        self.assertIn("\x1b[33m[WARN] review\x1b[0m", completed.stdout)
        self.assertIn("\x1b[31m[ERROR] unhealthy\x1b[0m", completed.stdout)
        self.assertIn("width=17", completed.stdout)

    def test_all_service_scope_uses_each_repository_highest_version(self) -> None:
        """Apply each image repository's real highest stable version.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(PROFILE_PROMPTS)}
source {bash_quote(IMAGE_ACTIONS)}
registry_stable_tags() {{
    case "$1" in
        registry/backend) printf '%s\n' 1.0.7 0.1.2 ;;
        registry/web) printf '%s\n' 1.0.8 1.0.6 ;;
    esac
}}
registry_verify_tag() {{ printf '{{"digest":"sha256:test","platformVerified":true}}\n'; }}
records=(
  'primary|Backend API|api|IMAGE_NAME|IMAGE_VERSION|registry/backend|0.1.2'
  'web|WebApp|web|WEB_IMAGE_NAME|WEB_IMAGE_VERSION|registry/web|1.0.6'
)
_select_release_image_scope "${{records[@]}}"
_prepare_release_image_updates
printf '%s\n' "${{IMAGE_UPDATE_ENV_ASSIGNMENTS[@]}}"
"""
        completed = run_bash(script, input_text="3\n\n\n\n")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("IMAGE_VERSION=1.0.7", completed.stdout)
        self.assertIn("WEB_IMAGE_VERSION=1.0.8", completed.stdout)

    def test_web_only_update_renders_deploys_and_verifies(self) -> None:
        """Update only WebApp through one automatic accepted deployment.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            scripts_directory = root / "scripts"
            scripts_directory.mkdir()
            environment = root / ".env"
            environment.write_text(
                "DEPLOYMENT_PROFILE_ID=example\n"
                "STACK_NAME=example\n"
                "IMAGE_NAME=registry/backend\n"
                "IMAGE_VERSION=0.1.2\n"
                "WEB_ENABLED=true\n"
                "WEB_IMAGE_NAME=registry/web\n"
                "WEB_IMAGE_VERSION=1.0.5\n",
                encoding="utf-8",
            )
            build_script = scripts_directory / "build-site-stack.sh"
            build_script.write_text(
                "#!/bin/bash\n"
                'printf "services:\\n  api:\\n    image: registry/backend:0.1.2\\n" '
                '> "$(dirname "$0")/../swarm-stack.yml"\n',
                encoding="utf-8",
            )
            build_script.chmod(0o755)
            script = f"""
source {bash_quote(PROFILE_PROMPTS)}
source {bash_quote(IMAGE_ACTIONS)}
PROJECT_ROOT={bash_quote(root)}
registry_stable_tags() {{ printf '%s\n' 1.0.6 1.0.5; }}
registry_verify_tag() {{ printf '{{"digest":"sha256:test","platformVerified":true}}\n'; }}
prompt_yes_no() {{ return 0; }}
load_root_env() {{
    DEPLOYMENT_PROFILE_ID=example
    STACK_NAME=example
    APP_STACK_FAMILY=api
    APP_PRIMARY_SERVICE=api
    APP_REQUIRES_WEB=true
    APP_RELEASE_VERSION_FLOOR=''
    IMAGE_NAME="$(grep '^IMAGE_NAME=' "$1/.env" | cut -d= -f2-)"
    IMAGE_VERSION="$(grep '^IMAGE_VERSION=' "$1/.env" | cut -d= -f2-)"
    WEB_ENABLED="$(grep '^WEB_ENABLED=' "$1/.env" | cut -d= -f2-)"
    WEB_IMAGE_NAME="$(grep '^WEB_IMAGE_NAME=' "$1/.env" | cut -d= -f2-)"
    WEB_IMAGE_VERSION="$(grep '^WEB_IMAGE_VERSION=' "$1/.env" | cut -d= -f2-)"
    return 0
}}
format_deployment_environment_file() {{ return 0; }}
backup_existing_files() {{ echo BACKUP-CREATED; }}
_deploy_configured_stack() {{
    printf 'DEPLOY-MODE=%s\n' "$1"
    DEPLOY_CONFIGURED_STACK_MUTATED=true
    return 0
}}
manage_service_images
"""
            completed = run_bash(
                script,
                input_text="2\n\n\n\n",
            )
            updated = environment.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("IMAGE_VERSION=0.1.2", updated)
        self.assertIn("WEB_IMAGE_VERSION=1.0.6", updated)
        self.assertIn("DEPLOY-MODE=confirmed", completed.stdout)
        self.assertIn("deployed and health-verified", completed.stdout)

    def test_logging_and_database_admin_toggles_share_verified_deploy(
        self,
    ) -> None:
        """Apply both quick actions through the common deployment boundary.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            scripts_directory = root / "scripts"
            scripts_directory.mkdir()
            environment = root / ".env"
            environment.write_text(
                "STACK_NAME=example\n"
                "ADVANCED_LOGGING_ENABLED=true\n"
                "PGADMIN_ENABLED=false\n"
                "PGADMIN_REPLICAS=0\n",
                encoding="utf-8",
            )
            build_script = scripts_directory / "build-site-stack.sh"
            build_script.write_text(
                "#!/bin/bash\n"
                'printf "services:\\n  api:\\n    image: example:1.0.0\\n" '
                '> "$(dirname "$0")/../swarm-stack.yml"\n',
                encoding="utf-8",
            )
            build_script.chmod(0o755)
            script = f"""
source {bash_quote(PROFILE_PROMPTS)}
source {bash_quote(MENU_RUNTIME_ACTIONS)}
PROJECT_ROOT={bash_quote(root)}
STACK_NAME=example
APP_ADMIN_UI_TYPE=pgadmin
APP_ADMIN_UI_DEFAULT_REPLICAS=1
ADVANCED_LOGGING_ENABLED=true
PGADMIN_ENABLED=false
PGADMIN_REPLICAS=0
prompt_yes_no() {{ return 0; }}
format_deployment_environment_file() {{ return 0; }}
backup_existing_files() {{ echo BACKUP-CREATED; }}
_stack_running() {{ return 0; }}
load_root_env() {{
    STACK_NAME=example
    ADVANCED_LOGGING_ENABLED="$(grep '^ADVANCED_LOGGING_ENABLED=' "$1/.env" | cut -d= -f2-)"
    PGADMIN_ENABLED="$(grep '^PGADMIN_ENABLED=' "$1/.env" | cut -d= -f2-)"
    PGADMIN_REPLICAS="$(grep '^PGADMIN_REPLICAS=' "$1/.env" | cut -d= -f2-)"
    return 0
}}
_deploy_configured_stack() {{
    printf 'DEPLOY-MODE=%s\n' "$1"
    DEPLOY_CONFIGURED_STACK_MUTATED=true
    return 0
}}
toggle_advanced_logging
toggle_database_admin_ui
"""
            completed = run_bash(script)
            updated = environment.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("ADVANCED_LOGGING_ENABLED=false", updated)
        self.assertIn("PGADMIN_ENABLED=true", updated)
        self.assertIn("PGADMIN_REPLICAS=1", updated)
        self.assertEqual(completed.stdout.count("DEPLOY-MODE=confirmed"), 2)
        self.assertEqual(
            completed.stdout.count("deployed and health-verified"),
            2,
        )


def bash_quote(path: Path) -> str:
    """Quote one filesystem path as a literal Bash word.

    Args:
        path: Path that may contain spaces or apostrophes.

    Returns:
        Safely single-quoted Bash representation.
    """

    return "'" + str(path).replace("'", "'\"'\"'") + "'"


def run_bash(
    script: str,
    *,
    input_text: str = "",
) -> subprocess.CompletedProcess[str]:
    """Execute an isolated Bash script and capture its output.

    Args:
        script: Bash source to execute.
        input_text: Terminal answers supplied on standard input.

    Returns:
        Completed process containing status, stdout, and stderr.
    """

    return subprocess.run(
        ["bash", "-c", script],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


if __name__ == "__main__":
    unittest.main()
