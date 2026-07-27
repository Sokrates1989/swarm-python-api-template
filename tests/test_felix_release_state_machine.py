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

from felix_release import health as release_health  # noqa: E402
from felix_release import state_machine  # noqa: E402
from felix_release.backup import (  # noqa: E402
    capture_previous_deployment,
    create_verified_backup,
)
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
    resolve_web_image_identity,
)
from felix_release.rollback import rollback_to_previous  # noqa: E402
from felix_site_contract import load_felix_site_profile  # noqa: E402
from felix_stack_renderer import render_stack  # noqa: E402
from tests.felix_profile_fixture import PRODUCTION_PROFILE  # noqa: E402
IMAGE_DIGEST = "sha256:" + ("a" * 64)
REDIS_DIGEST = "sha256:" + ("b" * 64)
WEB_DIGEST = "sha256:" + ("e" * 64)


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
        (self.root / ".env").write_text(
            "".join(
                f"{key}={value}\n" for key, value in PRODUCTION_PROFILE.items()
            ),
            encoding="utf-8",
        )
        self.profile = load_felix_site_profile(self.root)
        self.image = ImageIdentity(
            "sokrates1989/python-api-felix:0.1.1",
            f"sokrates1989/python-api-felix@{IMAGE_DIGEST}",
            IMAGE_DIGEST,
            "0.1.1",
            "c" * 40,
            "d" * 64,
            "amd64",
            "linux",
        )
        self.web_image = ImageIdentity(
            "sokrates1989/felix-webapp:1.0.5",
            f"sokrates1989/felix-webapp@{WEB_DIGEST}",
            WEB_DIGEST,
            "1.0.5",
            "f" * 40,
            None,
            "amd64",
            "linux",
            component="web",
            profile_fingerprint="9" * 64,
        )

    def _api_health_payload(self) -> dict[str, object]:
        """Build one exact healthy Felix API response fixture.

        Returns:
            Production runtime, migration, and Keycloak health mapping.
        """

        return {
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

    def _web_metadata_payload(self) -> dict[str, object]:
        """Build one exact healthy Felix WebApp metadata fixture.

        Returns:
            Public production WebApp release identity mapping.
        """

        return {
            "kind": "flutter-web-release",
            "appId": "felix",
            "appPath": "apps/felix",
            "environment": "production",
            "imageRepository": "sokrates1989/felix-webapp",
            "imageTag": "1.0.5",
            "profileFingerprint": "9" * 64,
            "sourceRevision": "f" * 40,
            "sourceDirty": False,
            "webOrigin": "https://felix-app.fe-wi.com",
            "backendOrigin": "https://api.felix-app.fe-wi.com",
            "keycloakIssuer": "https://keycloak.fe-wi.com/realms/felix-new",
            "keycloakRealm": "felix-new",
            "keycloakClientId": "felix-new-frontend",
        }

    def test_renderer_declares_automatic_start_first_rollback(self) -> None:
        """Require bounded automatic rollback in both public services."""

        stack = render_stack(self.profile)

        self.assertIn("failure_action: rollback", stack)
        self.assertIn("rollback_config:", stack)
        self.assertIn("monitor: 60s", stack)
        self.assertIn("order: start-first", stack)

    def test_digest_bound_stack_replaces_both_public_image_tags(self) -> None:
        """Deploy WebApp/API digests while preserving pinned data services."""

        stack = _digest_bound_stack(self.profile, self.image, self.web_image)

        self.assertIn(f'image: "{self.image.digest_reference}"', stack)
        self.assertNotIn(f'image: "{self.image.tag_reference}"', stack)
        self.assertIn(f'image: "{self.web_image.digest_reference}"', stack)
        self.assertNotIn(f'image: "{self.web_image.tag_reference}"', stack)
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
            _digest_bound_stack(self.profile, self.image, self.web_image),
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
                        "org.opencontainers.image.version": "0.1.1",
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

    def test_web_image_resolution_requires_exact_public_oci_identity(self) -> None:
        """Accept one published WebApp with exact profile and public labels."""

        inspect_payload = [
            {
                "RepoDigests": [self.web_image.digest_reference],
                "Architecture": "amd64",
                "Os": "linux",
                "Config": {
                    "Labels": {
                        "org.opencontainers.image.version": "1.0.5",
                        "org.opencontainers.image.revision": "f" * 40,
                        "com.felicitas_wisdom.app.id": "felix",
                        "com.felicitas_wisdom.profile.environment": "production",
                        "com.felicitas_wisdom.profile.fingerprint": "9" * 64,
                        "com.felicitas_wisdom.web.origin": (
                            "https://felix-app.fe-wi.com"
                        ),
                        "com.felicitas_wisdom.backend.origin": (
                            "https://api.felix-app.fe-wi.com"
                        ),
                        "com.felicitas_wisdom.keycloak.issuer": (
                            "https://keycloak.fe-wi.com/realms/felix-new"
                        ),
                        "com.felicitas_wisdom.keycloak.realm": "felix-new",
                        "com.felicitas_wisdom.keycloak.client_id": (
                            "felix-new-frontend"
                        ),
                    }
                },
            }
        ]
        command = (
            "docker",
            "image",
            "inspect",
            self.web_image.tag_reference,
        )
        runner = FakeRunner(
            {
                command: CommandResult(
                    command,
                    0,
                    json.dumps(inspect_payload),
                    "",
                )
            }
        )

        resolved = resolve_web_image_identity(runner, self.profile)

        self.assertEqual(resolved, self.web_image)

    def test_previous_deployment_captures_both_public_image_digests(self) -> None:
        """Capture exact WebApp/API state before a full-stack deployment."""

        stack_command = ("docker", "stack", "ls", "--format", "{{.Name}}")
        api_command = (
            "docker",
            "service",
            "inspect",
            "felix-new_api",
            "--format",
            "{{json .Spec.TaskTemplate.ContainerSpec.Image}}",
        )
        web_command = (
            "docker",
            "service",
            "inspect",
            "felix-new_web",
            "--format",
            "{{json .Spec.TaskTemplate.ContainerSpec.Image}}",
        )
        runner = FakeRunner(
            {
                stack_command: CommandResult(stack_command, 0, "felix-new\n", ""),
                api_command: CommandResult(
                    api_command,
                    0,
                    json.dumps(self.image.digest_reference),
                    "",
                ),
                web_command: CommandResult(
                    web_command,
                    0,
                    json.dumps(self.web_image.digest_reference),
                    "",
                ),
            }
        )

        previous = capture_previous_deployment(runner)

        self.assertTrue(previous.stack_exists)
        self.assertEqual(previous.image_digest, self.image.digest)
        self.assertEqual(previous.web_image_digest, self.web_image.digest)

    def test_failed_update_restores_both_prior_public_images(self) -> None:
        """Rollback WebApp/API services to their independently captured digests."""

        api_command = (
            "docker",
            "service",
            "inspect",
            "felix-new_api",
            "--format",
            "{{json .Spec.TaskTemplate.ContainerSpec.Image}}",
        )
        web_command = (
            "docker",
            "service",
            "inspect",
            "felix-new_web",
            "--format",
            "{{json .Spec.TaskTemplate.ContainerSpec.Image}}",
        )
        previous = PreviousDeployment(
            True,
            True,
            self.image.digest_reference,
            self.image.digest,
            True,
            self.web_image.digest_reference,
            self.web_image.digest,
        )
        runner = FakeRunner(
            {
                api_command: CommandResult(
                    api_command,
                    0,
                    json.dumps(self.image.digest_reference),
                    "",
                ),
                web_command: CommandResult(
                    web_command,
                    0,
                    json.dumps(self.web_image.digest_reference),
                    "",
                ),
            }
        )

        evidence = rollback_to_previous(runner, previous)

        self.assertEqual(evidence["mode"], "full-stack-service-rollback")
        self.assertEqual(
            evidence["services"]["api"]["restoredImage"],
            self.image.digest_reference,
        )
        self.assertEqual(
            evidence["services"]["web"]["restoredImage"],
            self.web_image.digest_reference,
        )

    def test_first_deploy_records_empty_database_beside_postgres_root(self) -> None:
        """Retain initial evidence under backups without misreading that path."""

        data_root = self.root / "data"
        (data_root / "postgres_data").mkdir(parents=True)
        profile = SimpleNamespace(
            deployment={"DATA_ROOT": str(data_root)},
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

        payload = self._api_health_payload()

        self.assertTrue(all(_validate_api_health(payload).values()))
        payload["migration_status"] = "failed"
        self.assertFalse(_validate_api_health(payload)["migration"])

    def test_strict_health_binds_web_and_api_digests_and_metadata(self) -> None:
        """Require both public services, HTTPS identities, and exact digests."""

        images = {
            "felix-new_web": self.web_image.digest_reference,
            "felix-new_api": self.image.digest_reference,
            "felix-new_postgres": f"postgres@{REDIS_DIGEST}",
            "felix-new_redis": f"redis@{REDIS_DIGEST}",
        }
        results: dict[tuple[str, ...], CommandResult] = {}
        for service_name, image in images.items():
            command = (
                "docker",
                "service",
                "inspect",
                service_name,
                "--format",
                "{{json .}}",
            )
            payload = {
                "Spec": {
                    "Mode": {"Replicated": {"Replicas": 1}},
                    "TaskTemplate": {"ContainerSpec": {"Image": image}},
                },
                "ServiceStatus": {"RunningTasks": 1, "DesiredTasks": 1},
            }
            results[command] = CommandResult(
                command,
                0,
                json.dumps(payload),
                "",
            )
        https_payloads = [
            self._web_metadata_payload(),
            self._api_health_payload(),
            {"IMAGE_TAG": "0.1.1"},
            {"issuer": "https://keycloak.fe-wi.com/realms/felix-new"},
            {"keys": [{"kid": "safe-public-key-id"}]},
        ]

        with (
            mock.patch.object(
                release_health,
                "_https_response",
                side_effect=[(200, b""), (401, b"")],
            ),
            mock.patch.object(
                release_health,
                "_https_json",
                side_effect=https_payloads,
            ),
        ):
            evidence = release_health.run_strict_health(
                FakeRunner(results),
                self.image,
                self.web_image,
                self.profile,
            )

        self.assertTrue(evidence.healthy)
        self.assertTrue(evidence.checks["webImageDigest"])
        self.assertTrue(evidence.checks["apiImageDigest"])
        self.assertRegex(str(evidence.web_metadata_fingerprint), r"^[0-9a-f]{64}$")

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
            self.web_image,
        )
        previous = PreviousDeployment(
            True,
            True,
            self.image.digest_reference,
            self.image.digest,
            True,
            self.web_image.digest_reference,
            self.web_image.digest,
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
            self.web_image,
        )
        previous = PreviousDeployment(
            True,
            True,
            self.image.digest_reference,
            self.image.digest,
            True,
            self.web_image.digest_reference,
            self.web_image.digest,
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
        web_inspect_command = (
            "docker",
            "service",
            "inspect",
            "felix-new_web",
            "--format",
            "{{json .}}",
        )
        web_version_command = (
            "docker",
            "service",
            "inspect",
            "felix-new_web",
            "--format",
            "{{json .Version.Index}}",
        )
        rolled_back_web_service = {
            "Version": {"Index": 10},
            "Spec": {
                "TaskTemplate": {
                    "ContainerSpec": {"Image": self.web_image.digest_reference}
                }
            },
            "UpdateStatus": {"State": "rollback_completed"},
        }
        runner = FakeRunner(
            {
                version_command: CommandResult(version_command, 0, "7", ""),
                web_version_command: CommandResult(
                    web_version_command,
                    0,
                    "9",
                    "",
                ),
                inspect_command: CommandResult(
                    inspect_command,
                    0,
                    json.dumps(rolled_back_service),
                    "",
                ),
                web_inspect_command: CommandResult(
                    web_inspect_command,
                    0,
                    json.dumps(rolled_back_web_service),
                    "",
                ),
            }
        )

        receipt_path = state_machine.FelixReleaseStateMachine(
            self.root,
            runner,
        ).failure_injection_drill()

        update_calls = [call for call in runner.calls if "update" in call]
        self.assertEqual(len(update_calls), 2)
        for update_call in update_calls:
            self.assertIn(f"redis@{REDIS_DIGEST}", update_call)
        create_marker.assert_called_once()
        verify_public_identity.assert_called_once()
        verify_marker.assert_called_once()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["state"], "rollback-drill-passed")
        self.assertEqual(
            receipt["rollback"]["services"]["api"]["dockerUpdateState"],
            "rollback_completed",
        )
        self.assertEqual(
            receipt["rollback"]["services"]["web"]["dockerUpdateState"],
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
