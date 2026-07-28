"""
Module: test_deployment_setup_safety.py

Description:
    Exercises the fail-closed deployment checks introduced by the shared setup
    wizard. Native Bash tests stub Docker and curl so they validate orchestration
    behavior without mutating a Swarm or contacting a deployed service.

Dependencies:
    - Python standard library.
    - Bash on Linux verification hosts.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
HEALTH_MODULE = REPOSITORY_ROOT / "setup" / "modules" / "health-check.sh"
SECRETS_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "docker-secrets-menu.sh"
)
ACTIONS_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "deployment-setup-actions.sh"
)
PROMPTS_MODULE = REPOSITORY_ROOT / "setup" / "modules" / "user-prompts.sh"
DEPLOYMENT_PROMPTS_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "deployment-profile-prompts.sh"
)
DEPLOYMENT_ROUTING_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "deployment-profile-routing.sh"
)
LEGACY_ENVIRONMENT_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "legacy-profile-environment.sh"
)
DEPLOY_MODULE = REPOSITORY_ROOT / "setup" / "modules" / "deploy-stack.sh"
RESTORE_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "menu-restore-actions.sh"
)
MENU_CONFIGURATION_MODULE = (
    REPOSITORY_ROOT
    / "setup"
    / "modules"
    / "menu-configuration-actions.sh"
)
NATIVE_BASH_AVAILABLE = (
    not sys.platform.startswith("win") and shutil.which("bash") is not None
)


@unittest.skipUnless(
    NATIVE_BASH_AVAILABLE,
    "Deployment safety smoke tests require native Bash.",
)
class DeploymentSetupSafetyTests(unittest.TestCase):
    """Verify deployment, secret, health, and network checks fail closed."""

    def test_replica_timeout_fails_health_acceptance(self) -> None:
        """Return nonzero when a service never reaches desired replicas.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(HEALTH_MODULE)}
docker() {{
    if [ "$1" = service ] && [ "$2" = ls ]; then
        case "$*" in
            *'{{{{.Name}}}}'*) echo demo_api ;;
            *'{{{{.Replicas}}}}'*) echo 0/1 ;;
        esac
        return 0
    fi
    return 0
}}
curl() {{ echo ok; }}
sleep() {{ return 0; }}
PRIMARY_SERVICE=api
STACK_FAMILY=api
HEALTH_CHECK_MAX_WAIT_SECONDS=1
HEALTH_CHECK_INTERVAL_SECONDS=1
check_deployment_health demo none none example.invalid 0 8083
"""
        completed = run_bash(script)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Deployment acceptance checks failed", completed.stdout)

    def test_direct_port_health_can_pass_acceptance(self) -> None:
        """Probe the manager's published port when no proxy is configured.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(HEALTH_MODULE)}
docker() {{
    if [ "$1" = service ] && [ "$2" = ls ]; then
        case "$*" in
            *'{{{{.Name}}}}'*) echo demo_api ;;
            *'{{{{.Replicas}}}}'*) echo 1/1 ;;
        esac
        return 0
    fi
    return 0
}}
curl() {{ echo ok; }}
PRIMARY_SERVICE=api
STACK_FAMILY=api
HEALTH_CHECK_MAX_WAIT_SECONDS=1
HEALTH_CHECK_INTERVAL_SECONDS=1
check_deployment_health demo none none example.invalid 0 8083
"""
        completed = run_bash(script)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("URL: http://127.0.0.1:8083/health", completed.stdout)
        self.assertIn("Deployment acceptance checks passed", completed.stdout)

    def test_internal_profile_has_no_public_ports_or_http_probe(self) -> None:
        """Keep Secure Messaging internal despite configured port defaults.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            environment_file = Path(temporary_directory) / ".env"
            script = f"""
_deployment_existing_value() {{ printf '%s' "$2"; }}
source {bash_quote(DEPLOYMENT_ROUTING_MODULE)}
source {bash_quote(LEGACY_ENVIRONMENT_MODULE)}
APP_IS_INTERNAL=true
APP_EXPOSURE_TRAEFIK=false
APP_EXPOSURE_PUBLISHED_PORTS=false
APP_ROUTING_API_PUBLISHED_PORT=8083
APP_ROUTING_WEB_PUBLISHED_PORT=8084
collect_deployment_proxy_and_ports
[ -z "$API_PUBLISHED_PORT" ]
[ -z "$WEB_PUBLISHED_PORT" ]
API_BASE_URL=http://secure_messaging_api:8080
DOMAIN=secure_messaging_api
INTERNAL_NETWORK=secure_messaging_internal
_write_legacy_routing_environment {bash_quote(environment_file)}
! grep -Eq '^API_PUBLISHED_PORT=[0-9]+' {bash_quote(environment_file)}
! grep -Eq '^PUBLISHED_PORT=[0-9]+' {bash_quote(environment_file)}

source {bash_quote(HEALTH_MODULE)}
docker() {{
    if [ "$1" = service ] && [ "$2" = ls ]; then
        case "$*" in
            *'{{{{.Name}}}}'*) echo secure_messaging_secure_messaging_api ;;
            *'{{{{.Replicas}}}}'*) echo 1/1 ;;
        esac
        return 0
    fi
    return 0
}}
curl() {{ echo CURL_SHOULD_NOT_RUN; return 1; }}
PRIMARY_SERVICE=secure_messaging_api
STACK_FAMILY=api
HEALTH_CHECK_MAX_WAIT_SECONDS=1
HEALTH_CHECK_INTERVAL_SECONDS=1
check_deployment_health \
    secure_messaging none none secure_messaging_api 0 8083
"""
            completed = run_bash(script)
            rendered_environment = environment_file.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("API_PUBLISHED_PORT=\n", rendered_environment)
        self.assertIn("PUBLISHED_PORT=\n", rendered_environment)
        self.assertNotIn("CURL_SHOULD_NOT_RUN", completed.stdout)
        self.assertNotIn("Testing API health endpoint", completed.stdout)
        self.assertIn("Deployment acceptance checks passed", completed.stdout)

    def test_failed_webapp_probe_fails_full_stack_acceptance(self) -> None:
        """Require both API and WebApp health paths for a public full stack.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(HEALTH_MODULE)}
docker() {{
    if [ "$1" = service ] && [ "$2" = ls ]; then
        case "$*" in
            *'{{{{.Name}}}}'*) printf 'demo_api\\ndemo_web\\n' ;;
            *'{{{{.Replicas}}}}'*) echo 1/1 ;;
        esac
        return 0
    fi
    return 0
}}
curl() {{
    case "$*" in
        *felix-app.example*) echo broken ;;
        *) echo ok ;;
    esac
}}
APP_REQUIRES_WEB=true
PRIMARY_SERVICE=api
STACK_FAMILY=api
HEALTH_CHECK_MAX_WAIT_SECONDS=1
HEALTH_CHECK_INTERVAL_SECONDS=1
check_deployment_health \
    demo none traefik api.felix-app.example 0 8083 \
    /ready felix-app.example 8084 /web-health
"""
        completed = run_bash(script)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "URL: https://api.felix-app.example/ready",
            completed.stdout,
        )
        self.assertIn(
            "URL: https://felix-app.example/web-health",
            completed.stdout,
        )
        self.assertIn("WebApp HTTP health check failed", completed.stdout)

    def test_missing_rendered_secret_blocks_deployment(self) -> None:
        """Detect exact missing secret names from the rendered stack.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            stack_file = Path(temporary_directory) / "swarm-stack.yml"
            stack_file.write_text(
                """services:
  api:
    image: example/api:1.0.0
secrets:
  "EXAMPLE_DB_PASSWORD":
    external: true
  EXAMPLE_CLIENT_SECRET:
    external: true
networks:
  backend:
    driver: overlay
""",
                encoding="utf-8",
            )
            script = f"""
source {bash_quote(SECRETS_MODULE)}
docker() {{
    [ "$1" = secret ] &&
        [ "$2" = inspect ] &&
        [ "$3" = EXAMPLE_DB_PASSWORD ]
}}
verify_required_docker_secrets {bash_quote(stack_file)}
"""
            completed = run_bash(script)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("[OK]      EXAMPLE_DB_PASSWORD", completed.stdout)
        self.assertIn("[MISSING] EXAMPLE_CLIENT_SECRET", completed.stdout)

    def test_secret_failure_prevents_stack_mutation(self) -> None:
        """Stop before conflict handling and deploy when secrets are missing.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            stack_file = Path(temporary_directory) / "swarm-stack.yml"
            stack_file.write_text("services: {}\n", encoding="utf-8")
            script = f"""
source {bash_quote(ACTIONS_MODULE)}
verify_required_docker_secrets() {{ echo secret-check-failed; return 1; }}
check_stack_conflict() {{ echo CONFLICT_CHECK_RAN; }}
deploy_stack() {{ echo DEPLOY_RAN; }}
PROJECT_ROOT={bash_quote(Path(temporary_directory))}
STACK_NAME=demo
_deploy_configured_stack
"""
            completed = run_bash(script)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("secret-check-failed", completed.stdout)
        self.assertNotIn("CONFLICT_CHECK_RAN", completed.stdout)
        self.assertNotIn("DEPLOY_RAN", completed.stdout)

    def test_traefik_network_requires_non_ingress_swarm_overlay(self) -> None:
        """Reject bridge and ingress networks while accepting a public overlay.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(PROMPTS_MODULE)}
docker() {{
    if [ "$1" = network ] && [ "$2" = inspect ]; then
        case "$5" in
            public) echo 'overlay|swarm|false' ;;
            ingress) echo 'overlay|swarm|true' ;;
            bridge) echo 'bridge|local|false' ;;
            *) return 1 ;;
        esac
        return 0
    fi
    return 1
}}
_swarm_overlay_network_is_usable public
! _swarm_overlay_network_is_usable ingress
! _swarm_overlay_network_is_usable bridge
! _swarm_overlay_network_is_usable missing
"""
        completed = run_bash(script)

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_deployment_values_reject_shell_metacharacters(self) -> None:
        """Reject values that could become shell or Compose expressions.

        Returns:
            Nothing.
        """

        script = f"""
source {bash_quote(DEPLOYMENT_PROMPTS_MODULE)}
! _deployment_value_is_valid domain '$(touch /tmp/unsafe).example.com'
! _deployment_value_is_valid path '/swarm/$(id)'
! _deployment_value_is_valid identifier 'user;id'
! _deployment_value_is_valid tag '1.0.0|next'
_deployment_value_is_valid domain 'api.example.com'
_deployment_value_is_valid path '/swarm/volumes/example'
"""
        completed = run_bash(script)

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_environment_restore_rebuilds_matching_stack_immediately(self) -> None:
        """Replace a stale stack artifact before restored config can deploy.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            scripts_directory = root / "scripts"
            scripts_directory.mkdir()
            (root / ".env").write_text(
                "DEPLOYMENT_PROFILE_ID=old\n",
                encoding="utf-8",
            )
            (root / "swarm-stack.yml").write_text(
                "profile: old\n",
                encoding="utf-8",
            )
            saved_environment = root / "saved.env"
            saved_environment.write_text(
                "DEPLOYMENT_PROFILE_ID=new\n",
                encoding="utf-8",
            )
            renderer = scripts_directory / "build-site-stack.sh"
            renderer.write_text(
                '#!/bin/bash\n'
                'grep -q "^DEPLOYMENT_PROFILE_ID=new$" '
                '"$(dirname "$0")/../.env" || exit 1\n'
                'printf "profile: new\\n" > '
                '"$(dirname "$0")/../swarm-stack.yml"\n',
                encoding="utf-8",
            )
            script = f"""
source {bash_quote(RESTORE_MODULE)}
load_root_env() {{
    grep -q '^DEPLOYMENT_PROFILE_ID=new$' "$1/.env"
}}
printf '%s\\n' {bash_quote(saved_environment)} |
    restore_deployment_environment {bash_quote(root)}
"""
            completed = run_bash(script)
            rendered = (root / "swarm-stack.yml").read_text(encoding="utf-8")
            backups = list(root.glob("swarm-stack.yml.backup.*"))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(rendered, "profile: new\n")
        self.assertEqual(len(backups), 1)
        self.assertIn("rebuilt the matching swarm-stack.yml", completed.stdout)

    def test_failed_restore_cannot_leave_partial_stack_active(self) -> None:
        """Roll back both artifacts when the selected renderer fails.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            scripts_directory = root / "scripts"
            scripts_directory.mkdir()
            (root / ".env").write_text(
                "DEPLOYMENT_PROFILE_ID=old\n",
                encoding="utf-8",
            )
            (root / "swarm-stack.yml").write_text(
                "profile: old\n",
                encoding="utf-8",
            )
            saved_environment = root / "saved.env"
            saved_environment.write_text(
                "DEPLOYMENT_PROFILE_ID=new\n",
                encoding="utf-8",
            )
            renderer = scripts_directory / "build-site-stack.sh"
            renderer.write_text(
                '#!/bin/bash\n'
                'printf "profile: partial\\n" > '
                '"$(dirname "$0")/../swarm-stack.yml"\n'
                "exit 1\n",
                encoding="utf-8",
            )
            script = f"""
source {bash_quote(RESTORE_MODULE)}
load_root_env() {{
    grep -q '^DEPLOYMENT_PROFILE_ID=' "$1/.env"
}}
printf '%s\\n' {bash_quote(saved_environment)} |
    restore_deployment_environment {bash_quote(root)}
"""
            completed = run_bash(script)
            active_environment = (root / ".env").read_text(encoding="utf-8")
            active_stack = (root / "swarm-stack.yml").read_text(
                encoding="utf-8"
            )
            failed_stacks = list(root.glob("swarm-stack.yml.failed.*"))
            failed_stack_content = failed_stacks[0].read_text(
                encoding="utf-8"
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(active_environment, "DEPLOYMENT_PROFILE_ID=old\n")
        self.assertEqual(active_stack, "profile: old\n")
        self.assertEqual(len(failed_stacks), 1)
        self.assertEqual(failed_stack_content, "profile: partial\n")

    def test_secret_restore_validates_before_stack_removal(self) -> None:
        """Reject an unsafe saved file before asking Docker to remove a stack.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            values_file = Path(temporary_directory) / "secrets.env"
            values_file.write_text("undeclared=value\n", encoding="utf-8")
            script = f"""
source {bash_quote(RESTORE_MODULE)}
validate_profile_secret_values_file() {{
    echo validation-ran
    return 1
}}
docker() {{ echo DOCKER_RAN; return 0; }}
printf '%s\\n' {bash_quote(values_file)} |
    restore_profile_secrets demo
"""
            completed = run_bash(script)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("validation-ran", completed.stdout)
        self.assertNotIn("DOCKER_RAN", completed.stdout)

    def test_failed_wizard_action_still_reloads_new_configuration(self) -> None:
        """Refresh menu globals even when a later wizard action fails.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            setup_directory = root / "setup"
            setup_directory.mkdir()
            wizard = setup_directory / "setup-wizard.sh"
            wizard.write_text(
                '#!/bin/bash\n'
                'printf "DEPLOYMENT_PROFILE_ID=new\\n" > '
                '"$(dirname "$0")/../.env"\n'
                "exit 1\n",
                encoding="utf-8",
            )
            wizard.chmod(0o755)
            script = f"""
PROJECT_ROOT={bash_quote(root)}
source {bash_quote(MENU_CONFIGURATION_MODULE)}
load_root_env() {{
    ACTIVE_PROFILE="$(cut -d= -f2 "$1/.env")"
    return 0
}}
_run_shared_reconfiguration test
status=$?
printf 'STATUS=%s\\nACTIVE=%s\\n' "$status" "$ACTIVE_PROFILE"
[ "$status" -eq 1 ] && [ "$ACTIVE_PROFILE" = new ]
"""
            completed = run_bash(script)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("STATUS=1", completed.stdout)
        self.assertIn("ACTIVE=new", completed.stdout)


class DeploymentDotenvStaticTests(unittest.TestCase):
    """Protect the non-executable dotenv deployment boundary on every host."""

    def test_deploy_uses_sanitized_compose_env_file(self) -> None:
        """Parse generated dotenv as data without sourcing it.

        Returns:
            Nothing.
        """

        source = DEPLOY_MODULE.read_text(encoding="utf-8")

        self.assertIn("env -i", source)
        self.assertIn("--env-file", source)
        self.assertNotIn('source "$env_file"', source)
        self.assertNotIn("set -a", source)


def bash_quote(path: Path) -> str:
    """Quote one filesystem path as a Bash word.

    Args:
        path: Path that may contain spaces or apostrophes.

    Returns:
        Single-quoted Bash representation.
    """

    return "'" + str(path).replace("'", "'\"'\"'") + "'"


def run_bash(script: str) -> subprocess.CompletedProcess[str]:
    """Execute an isolated Bash test script and capture its output.

    Args:
        script: Bash source to execute.

    Returns:
        Completed process containing exit status, stdout, and stderr.
    """

    return subprocess.run(
        ["bash", "-c", script],
        text=True,
        capture_output=True,
        check=False,
    )


if __name__ == "__main__":
    unittest.main()
