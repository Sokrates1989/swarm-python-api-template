"""Tests for the strict Felix candidate deploy and rollback state machine.

The suite is standard-library-only. It uses isolated profiles and shell-free
command fakes for failure paths, with opt-in real Docker Compose/Swarm parsing
through ``RUN_DOCKER_COMPOSE_TESTS=1``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from felix_release import state_machine  # noqa: E402
from felix_release.backup import create_verified_backup  # noqa: E402
from felix_release.command import CommandResult  # noqa: E402
from felix_release.errors import FelixReleaseError  # noqa: E402
from felix_release.health import _validate_api_health  # noqa: E402
from felix_release.models import (  # noqa: E402
    BackupEvidence,
    HealthEvidence,
    ImageIdentity,
    PreflightEvidence,
    PreviousDeployment,
)
from felix_release.preflight import (  # noqa: E402
    _digest_bound_stack,
    resolve_image_identity,
)
from felix_site_contract import load_felix_site_profile  # noqa: E402
from felix_stack_renderer import render_stack  # noqa: E402


PRODUCTION_PROFILE = {
    "PROFILE_SCHEMA_VERSION": "1",
    "APP_ID": "felix",
    "APP_ENVIRONMENT": "production",
    "APP_PROFILE": "felix",
    "BACKEND_APP_ID": "felix",
    "BACKEND_DATA_PROFILE": "postgresql",
    "AUTH_PROVIDER": "keycloak",
    "API_BASE_URL": "https://api.felix-app.fe-wi.com",
    "DOMAIN": "api.felix-app.fe-wi.com",
    "CORS_ORIGINS": "https://felix-app.fe-wi.com",
    "KEYCLOAK_BASE_URL": "https://keycloak.fe-wi.com",
    "KEYCLOAK_ISSUER_URL": "https://keycloak.fe-wi.com/realms/felix-new",
    "KEYCLOAK_REALM": "felix-new",
    "KEYCLOAK_AUDIENCE": "felix-new-backend",
    "KEYCLOAK_FRONTEND_CLIENT_ID": "felix-new-frontend",
    "STACK_NAME": "felix-new",
}
IMAGE_DIGEST = "sha256:" + ("a" * 64)
REDIS_DIGEST = "sha256:" + ("b" * 64)


class FakeRunner:
    """Return configured shell-free command results and retain invocations."""

    def __init__(self, results: dict[tuple[str, ...], CommandResult] | None = None):
        """Initialize one deterministic command fake.

        Args:
            results: Optional exact argument-vector result mapping.
        """

        self.results = results or {}
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        arguments: list[str],
        *,
        cwd: Path | None = None,
        input_text: str | None = None,
        check: bool = True,
    ) -> CommandResult:
        """Return one configured result or a successful empty result.

        Args:
            arguments: Exact argument vector.
            cwd: Ignored optional working directory.
            input_text: Ignored optional stdin text.
            check: Whether a configured failure should raise.

        Returns:
            Configured or default command result.

        Raises:
            FelixReleaseError: If a checked configured result is nonzero.
        """

        del cwd, input_text
        key = tuple(arguments)
        self.calls.append(key)
        result = self.results.get(key, CommandResult(key, 0, "", ""))
        if check and result.return_code != 0:
            raise FelixReleaseError("Configured fake command failed.")
        return result


class FelixReleaseStateMachineTests(unittest.TestCase):
    """Verify immutable identity, rollback, backup, and health enforcement."""

    def setUp(self) -> None:
        """Create a valid isolated Felix profile.

        Returns:
            None.
        """

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        config_directory = self.root / "site-configs"
        config_directory.mkdir()
        config = (REPOSITORY_ROOT / "site-configs" / "felix.json").read_text(
            encoding="utf-8"
        )
        (config_directory / "felix.json").write_text(config, encoding="utf-8")
        (self.root / "prod.env").write_text(
            "".join(
                f"{key}={value}\n" for key, value in PRODUCTION_PROFILE.items()
            ),
            encoding="utf-8",
        )
        self.profile = load_felix_site_profile(self.root)
        self.image = ImageIdentity(
            "sokrates1989/python-api-felix:0.1.0",
            f"sokrates1989/python-api-felix@{IMAGE_DIGEST}",
            IMAGE_DIGEST,
            "0.1.0",
            "c" * 40,
            "d" * 64,
            "amd64",
            "linux",
        )

    def test_renderer_declares_automatic_start_first_rollback(self) -> None:
        """Require bounded automatic rollback in the candidate API service."""

        stack = render_stack(self.profile)

        self.assertIn("failure_action: rollback", stack)
        self.assertIn("rollback_config:", stack)
        self.assertIn("monitor: 60s", stack)
        self.assertIn("order: start-first", stack)

    def test_digest_bound_stack_replaces_only_candidate_api_tag(self) -> None:
        """Deploy the API by immutable digest while preserving pinned services."""

        stack = _digest_bound_stack(self.profile, self.image)

        self.assertIn(f'image: "{self.image.digest_reference}"', stack)
        self.assertNotIn(f'image: "{self.image.tag_reference}"', stack)
        self.assertIn("redis@sha256:", stack)
        self.assertIn("postgres@sha256:", stack)

    @unittest.skipUnless(
        os.environ.get("RUN_DOCKER_COMPOSE_TESTS") == "1",
        "set RUN_DOCKER_COMPOSE_TESTS=1 for the host integration gate",
    )
    def test_digest_stack_passes_real_docker_stack_config(self) -> None:
        """Require Docker Swarm Compose parsing of the immutable stack."""

        stack_path = self.root / "digest-stack.yml"
        stack_path.write_text(
            _digest_bound_stack(self.profile, self.image),
            encoding="utf-8",
        )

        completed = subprocess.run(
            ["docker", "stack", "config", "--compose-file", str(stack_path)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr or completed.stdout,
        )

    def test_image_resolution_requires_registry_digest_and_oci_identity(self) -> None:
        """Accept one published linux/amd64 image with exact Felix OCI labels."""

        inspect_payload = [
            {
                "RepoDigests": [self.image.digest_reference],
                "Architecture": "amd64",
                "Os": "linux",
                "Config": {
                    "Labels": {
                        "org.opencontainers.image.version": "0.1.0",
                        "org.opencontainers.image.revision": "c" * 40,
                        "com.fe-wi.dependency-lock-sha256": "d" * 64,
                        "com.fe-wi.app-profile": "felix",
                        "com.fe-wi.backend-app-id": "felix",
                    }
                },
            }
        ]
        inspect_command = (
            "docker",
            "image",
            "inspect",
            self.image.tag_reference,
        )
        runner = FakeRunner(
            {
                inspect_command: CommandResult(
                    inspect_command,
                    0,
                    json.dumps(inspect_payload),
                    "",
                )
            }
        )

        resolved = resolve_image_identity(runner, self.profile)

        self.assertEqual(resolved, self.image)

    def test_first_deploy_records_empty_database_beside_postgres_root(self) -> None:
        """Retain initial evidence under backups without misreading that path."""

        data_root = self.root / "data"
        (data_root / "postgres").mkdir(parents=True)
        profile = SimpleNamespace(
            data={"storage": {"dataRoot": str(data_root)}},
            environment={"DB_USER": "felix", "DB_NAME": "felix"},
        )

        evidence = create_verified_backup(
            FakeRunner(),
            profile,
            PreviousDeployment(False, False, None, None),
            "operation",
        )

        self.assertTrue(evidence.verified)
        self.assertEqual(
            evidence.path.parent.parent,
            data_root / "backups" / "release",
        )

    def test_health_identity_requires_every_production_runtime_field(self) -> None:
        """Reject a health payload when any required identity field drifts."""

        payload = {
            "status": "OK",
            "app_environment": "production",
            "app_profile": "felix",
            "backend_app_id": "felix",
            "build_backend_app_id": "felix",
            "backend_data_profile": "postgresql",
            "provider_profile": "sql",
            "startup_probe_status": "success",
            "startup_complete": True,
            "migration_status": "success",
            "auth_provider": "keycloak",
            "keycloak": {
                "configured": True,
                "realm": "felix-new",
                "issuer": "https://keycloak.fe-wi.com/realms/felix-new",
                "audience": "felix-new-backend",
                "audience_enforced": True,
            },
        }

        self.assertTrue(all(_validate_api_health(payload).values()))
        payload["migration_status"] = "failed"
        self.assertFalse(_validate_api_health(payload)["migration"])

    @mock.patch.object(state_machine, "_rollback_to_previous")
    @mock.patch.object(state_machine, "_wait_for_health")
    @mock.patch.object(state_machine, "create_verified_backup")
    @mock.patch.object(state_machine, "capture_previous_deployment")
    @mock.patch.object(state_machine, "load_felix_site_profile")
    @mock.patch.object(state_machine, "run_preflight")
    def test_failed_candidate_health_rolls_back_captured_image(
        self,
        run_preflight: mock.Mock,
        load_profile: mock.Mock,
        capture_previous: mock.Mock,
        create_backup: mock.Mock,
        wait_for_health: mock.Mock,
        rollback: mock.Mock,
    ) -> None:
        """Rollback the candidate when strict health fails after deploy starts."""

        preflight = PreflightEvidence(
            "f" * 64,
            self.image,
            self.root / "deploy-stack.yml",
            (),
            (),
            {"ready": True},
        )
        previous = PreviousDeployment(
            True,
            True,
            self.image.digest_reference,
            self.image.digest,
        )
        backup_path = self.root / "backup.pgdump"
        backup_path.write_bytes(b"verified-backup")
        run_preflight.return_value = preflight
        load_profile.return_value = SimpleNamespace()
        capture_previous.return_value = previous
        create_backup.return_value = BackupEvidence(
            "pg-dump",
            backup_path,
            "e" * 64,
            backup_path.stat().st_size,
            True,
        )
        wait_for_health.side_effect = FelixReleaseError("candidate unhealthy")
        rollback.return_value = {
            "performed": True,
            "mode": "service-rollback",
            "restoredImage": previous.image_reference,
        }
        runner = FakeRunner()

        with self.assertRaisesRegex(FelixReleaseError, "candidate unhealthy"):
            state_machine.FelixReleaseStateMachine(self.root, runner).deploy()

        rollback.assert_called_once_with(runner, previous)
        deploy_call = next(call for call in runner.calls if "deploy" in call)
        self.assertIn("felix-new", deploy_call)
        receipts = list(
            (self.root / state_machine.RECEIPT_DIRECTORY).glob("*.json")
        )
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(receipt["state"], "rolled-back")

    @mock.patch.object(state_machine, "verify_continuity_marker")
    @mock.patch.object(state_machine, "create_continuity_marker")
    @mock.patch.object(state_machine, "verify_public_identity_continuity")
    @mock.patch.object(state_machine, "run_strict_health")
    @mock.patch.object(state_machine, "capture_previous_deployment")
    @mock.patch.object(state_machine, "load_felix_site_profile")
    @mock.patch.object(state_machine, "run_preflight")
    def test_failure_drill_restores_digest_and_verifies_data(
        self,
        run_preflight: mock.Mock,
        load_profile: mock.Mock,
        capture_previous: mock.Mock,
        strict_health: mock.Mock,
        verify_public_identity: mock.Mock,
        create_marker: mock.Mock,
        verify_marker: mock.Mock,
    ) -> None:
        """Inject a pinned non-API image, rollback, and prove marker continuity."""

        health = HealthEvidence({"healthy": True}, {}, "e" * 64, 0)
        preflight = PreflightEvidence(
            "f" * 64,
            self.image,
            self.root / "deploy-stack.yml",
            (),
            (),
            {"ready": True},
        )
        previous = PreviousDeployment(
            True,
            True,
            self.image.digest_reference,
            self.image.digest,
        )
        profile = SimpleNamespace(
            data={"services": {"redisImage": f"redis@{REDIS_DIGEST}"}}
        )
        run_preflight.return_value = preflight
        load_profile.return_value = profile
        capture_previous.return_value = previous
        strict_health.side_effect = [health, health]
        inspect_command = (
            "docker",
            "service",
            "inspect",
            "felix-new_api",
            "--format",
            "{{json .}}",
        )
        rolled_back_service = {
            "Version": {"Index": 8},
            "Spec": {
                "TaskTemplate": {
                    "ContainerSpec": {"Image": self.image.digest_reference}
                }
            },
            "UpdateStatus": {"State": "rollback_completed"},
        }
        version_command = (
            "docker",
            "service",
            "inspect",
            "felix-new_api",
            "--format",
            "{{json .Version.Index}}",
        )
        runner = FakeRunner(
            {
                version_command: CommandResult(version_command, 0, "7", ""),
                inspect_command: CommandResult(
                    inspect_command,
                    0,
                    json.dumps(rolled_back_service),
                    "",
                )
            }
        )

        receipt_path = state_machine.FelixReleaseStateMachine(
            self.root,
            runner,
        ).failure_injection_drill()

        update_call = next(call for call in runner.calls if "update" in call)
        self.assertIn(f"redis@{REDIS_DIGEST}", update_call)
        create_marker.assert_called_once()
        verify_public_identity.assert_called_once()
        verify_marker.assert_called_once()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["state"], "rollback-drill-passed")
        self.assertEqual(
            receipt["rollback"]["dockerUpdateState"],
            "rollback_completed",
        )
        self.assertTrue(receipt["rollback"]["dataContinuityVerified"])

    def test_candidate_logs_are_redacted_before_output(self) -> None:
        """Remove credential and bearer values from the operator log command."""

        command = (
            "docker",
            "service",
            "logs",
            "--raw",
            "--tail",
            "200",
            "felix-new_api",
        )
        runner = FakeRunner(
            {
                command: CommandResult(
                    command,
                    0,
                    "password=hidden Authorization: Bearer token.value\n",
                    "",
                )
            }
        )

        output = state_machine.FelixReleaseStateMachine(
            self.root,
            runner,
        ).sanitized_logs()

        self.assertNotIn("hidden", output)
        self.assertNotIn("token.value", output)
        self.assertIn("[REDACTED]", output)


if __name__ == "__main__":
    unittest.main()
