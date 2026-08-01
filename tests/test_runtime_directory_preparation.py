"""
Module: test_runtime_directory_preparation.py

Description:
    Verifies that shared Swarm deployment actions prepare API bind mounts for
    the non-root image identity before stack mutation. Docker and ownership
    commands are stubbed, so the tests never mutate host ownership or Swarm.

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
DATA_DIRECTORIES_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "data-dirs.sh"
)
DEPLOYMENT_ACTIONS_MODULE = (
    REPOSITORY_ROOT / "setup" / "modules" / "deployment-setup-actions.sh"
)
QUICK_START_SCRIPT = REPOSITORY_ROOT / "quick-start.sh"
NATIVE_BASH_AVAILABLE = (
    not sys.platform.startswith("win") and shutil.which("bash") is not None
)


@unittest.skipUnless(
    NATIVE_BASH_AVAILABLE,
    "Runtime-directory tests require native Bash.",
)
class RuntimeDirectoryPreparationTests(unittest.TestCase):
    """Verify API bind mounts are writable before any Swarm deployment."""

    def test_api_profile_prepares_log_and_backup_ownership(self) -> None:
        """Apply UID/GID 10001 and owner write access to API bind mounts.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            data_root = Path(temporary_directory) / "deployment-data"
            script = f"""
source {bash_quote(DATA_DIRECTORIES_MODULE)}
chown() {{ printf 'CHOWN %s\n' "$*"; return 0; }}
chmod() {{ printf 'CHMOD %s\n' "$*"; return 0; }}
STACK_FAMILY=api
APP_REQUIRES_REDIS=false
PGADMIN_ENABLED=false
create_data_directories {bash_quote(data_root)} none none
test -d {bash_quote(data_root / 'logs' / 'api')}
test -d {bash_quote(data_root / 'backups')}
"""
            completed = run_bash(script)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn(
            f"CHOWN -R -- 10001:10001 {data_root / 'logs' / 'api'}",
            completed.stdout,
        )
        self.assertIn(
            f"CHOWN -R -- 10001:10001 {data_root / 'backups'}",
            completed.stdout,
        )
        self.assertEqual(completed.stdout.count("CHMOD -R u+rwX --"), 2)

    def test_nginx_profile_does_not_create_api_mounts(self) -> None:
        """Leave API-only log and backup paths absent for nginx profiles.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            data_root = Path(temporary_directory) / "nginx-data"
            script = f"""
source {bash_quote(DATA_DIRECTORIES_MODULE)}
chown() {{ echo CHOWN_SHOULD_NOT_RUN; return 1; }}
chmod() {{ echo CHMOD_SHOULD_NOT_RUN; return 1; }}
STACK_FAMILY=nginx
create_data_directories {bash_quote(data_root)} none none
test ! -e {bash_quote(data_root / 'logs' / 'api')}
test ! -e {bash_quote(data_root / 'backups')}
"""
            completed = run_bash(script)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("CHOWN_SHOULD_NOT_RUN", completed.stdout)
        self.assertNotIn("CHMOD_SHOULD_NOT_RUN", completed.stdout)

    def test_invalid_api_runtime_identity_fails_closed(self) -> None:
        """Reject an unsafe nonnumeric runtime UID before ownership mutation.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            data_root = Path(temporary_directory) / "invalid-identity"
            script = f"""
API_RUNTIME_UID=not-a-uid
source {bash_quote(DATA_DIRECTORIES_MODULE)}
chown() {{ echo CHOWN_SHOULD_NOT_RUN; return 1; }}
STACK_FAMILY=api
create_data_directories {bash_quote(data_root)} none none
"""
            completed = run_bash(script)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("API_RUNTIME_UID must be a numeric UID", completed.stdout)
        self.assertNotIn("CHOWN_SHOULD_NOT_RUN", completed.stdout)

    def test_direct_deploy_prepares_directories_before_secret_check(self) -> None:
        """Run directory repair before secret validation and stack mutation.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "swarm-stack.yml").write_text(
                "services: {}\n",
                encoding="utf-8",
            )
            script = f"""
source {bash_quote(DEPLOYMENT_ACTIONS_MODULE)}
create_data_directories() {{ echo STEP-DIRECTORIES; return 0; }}
verify_required_docker_secrets() {{ echo STEP-SECRETS; return 0; }}
_prepare_profile_external_network() {{ echo STEP-NETWORK; return 0; }}
deploy_stack() {{ echo STEP-DEPLOY; return 0; }}
_check_configured_stack_health() {{ echo STEP-HEALTH; return 0; }}
PROJECT_ROOT={bash_quote(root)}
STACK_NAME=example
DATA_ROOT=/swarm/example
DB_TYPE=postgresql
DB_MODE=local
_deploy_configured_stack
"""
            completed = run_bash(script)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        ordered_steps = [
            completed.stdout.index(marker)
            for marker in (
                "STEP-DIRECTORIES",
                "STEP-SECRETS",
                "STEP-NETWORK",
                "STEP-DEPLOY",
                "STEP-HEALTH",
            )
        ]
        self.assertEqual(ordered_steps, sorted(ordered_steps))

    def test_directory_failure_blocks_secret_check_and_deploy(self) -> None:
        """Fail closed before secrets or Swarm change when chown is impossible.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "swarm-stack.yml").write_text(
                "services: {}\n",
                encoding="utf-8",
            )
            script = f"""
source {bash_quote(DEPLOYMENT_ACTIONS_MODULE)}
create_data_directories() {{ echo DIRECTORY_REPAIR_FAILED; return 17; }}
verify_required_docker_secrets() {{ echo SECRET_CHECK_SHOULD_NOT_RUN; }}
deploy_stack() {{ echo DEPLOY_SHOULD_NOT_RUN; }}
PROJECT_ROOT={bash_quote(root)}
STACK_NAME=example
DATA_ROOT=/swarm/example
DB_TYPE=postgresql
DB_MODE=local
_deploy_configured_stack
"""
            completed = run_bash(script)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("DIRECTORY_REPAIR_FAILED", completed.stdout)
        self.assertNotIn("SECRET_CHECK_SHOULD_NOT_RUN", completed.stdout)
        self.assertNotIn("DEPLOY_SHOULD_NOT_RUN", completed.stdout)

    def test_quick_start_loads_data_directory_module(self) -> None:
        """Keep direct main-menu deployments wired to directory preparation.

        Returns:
            Nothing.
        """

        quick_start = QUICK_START_SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            'source "${PROJECT_ROOT}/setup/modules/data-dirs.sh"',
            quick_start,
        )


def bash_quote(value: Path | str) -> str:
    """Quote one filesystem or scalar value for a generated Bash script.

    Args:
        value: Value that must be represented as one Bash argument.

    Returns:
        A single-quoted Bash token with embedded quotes escaped.
    """

    text = str(value)
    return "'" + text.replace("'", "'\\''") + "'"


def run_bash(script: str) -> subprocess.CompletedProcess[str]:
    """Execute a Bash test script and capture its diagnostic output.

    Args:
        script: Bash source to execute.

    Returns:
        The completed process without raising for nonzero exit status.
    """

    return subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )


if __name__ == "__main__":
    unittest.main()
