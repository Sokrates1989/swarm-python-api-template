"""
Module: test_keycloak_profile_secret_bridge.py

Description:
    Verifies that Docker secret discovery distinguishes a genuinely absent
    secret from Docker daemon, authorization, and Swarm-manager failures.

Dependencies:
    - Python standard library.
    - scripts/keycloak_profile_secret_bridge.py.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from keycloak_profile_secret_bridge import (  # noqa: E402
    KeycloakSecretBridgeError,
    _docker,
    build_client_secret_value_evidence,
    build_opaque_client_secret_value_evidence,
    docker_secret_exists,
    write_docker_secret,
)


class KeycloakProfileSecretBridgeTests(unittest.TestCase):
    """Exercise fail-closed Docker secret inspection."""

    def test_observed_secret_evidence_discloses_no_value_characters(
        self,
    ) -> None:
        """Report stable proof metadata without returning credential text.

        Returns:
            Nothing.
        """

        secret = "keycloak-generated-sensitive-sentinel"
        evidence = build_client_secret_value_evidence(
            secret,
            "EXAMPLE_KEYCLOAK_SECRET",
        )

        self.assertIs(evidence["observedThisRun"], True)
        self.assertEqual(evidence["source"], "keycloak-admin-api")
        self.assertIs(evidence["distinctFromDockerSecretName"], True)
        self.assertEqual(evidence["length"], len(secret))
        self.assertEqual(
            evidence["sha256Prefix"],
            hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16],
        )
        self.assertNotIn(secret, json.dumps(evidence))

    def test_secret_value_cannot_equal_docker_secret_name(self) -> None:
        """Reject an ambiguous credential before proof or publication.

        Returns:
            Nothing.
        """

        with self.assertRaisesRegex(
            KeycloakSecretBridgeError,
            "equal to the Docker secret name",
        ):
            build_client_secret_value_evidence(
                "EXAMPLE_KEYCLOAK_SECRET",
                "EXAMPLE_KEYCLOAK_SECRET",
            )

    def test_existing_opaque_secret_has_no_invented_value_evidence(
        self,
    ) -> None:
        """Mark value evidence unavailable when Swarm cannot reveal it.

        Returns:
            Nothing.
        """

        evidence = build_opaque_client_secret_value_evidence()

        self.assertIs(evidence["observedThisRun"], False)
        self.assertEqual(
            evidence["source"],
            "existing-docker-secret-opaque",
        )
        self.assertIsNone(evidence["distinctFromDockerSecretName"])
        self.assertIsNone(evidence["length"])
        self.assertIsNone(evidence["sha256Prefix"])

    def test_missing_secret_is_reported_as_absent(self) -> None:
        """Return false only for Docker's explicit missing-secret response.

        Returns:
            Nothing.
        """

        result = subprocess.CompletedProcess(
            args=["docker", "secret", "inspect"],
            returncode=1,
            stdout=b"[]\n",
            stderr=(
                b"Error response from daemon: secret "
                b"EXAMPLE_KEYCLOAK_SECRET not found\n"
            ),
        )
        with patch(
            "keycloak_profile_secret_bridge._docker",
            return_value=result,
        ):
            self.assertFalse(
                docker_secret_exists("EXAMPLE_KEYCLOAK_SECRET")
            )

    def test_operational_inspection_failure_is_not_treated_as_absent(
        self,
    ) -> None:
        """Fail before mutation when Docker cannot inspect Swarm secrets.

        Returns:
            Nothing.
        """

        result = subprocess.CompletedProcess(
            args=["docker", "secret", "inspect"],
            returncode=1,
            stdout=b"",
            stderr=b"This node is not a swarm manager.\n",
        )
        with (
            patch(
                "keycloak_profile_secret_bridge._docker",
                return_value=result,
            ),
            self.assertRaisesRegex(
                KeycloakSecretBridgeError,
                "authorized Docker Swarm manager",
            ),
        ):
            docker_secret_exists("EXAMPLE_KEYCLOAK_SECRET")

    def test_docker_receives_secret_only_on_standard_input(self) -> None:
        """Keep credential material out of Docker arguments and output.

        Returns:
            Nothing.
        """

        with patch(
            "keycloak_profile_secret_bridge.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["docker"],
                returncode=0,
                stdout=b"",
                stderr=b"",
            ),
        ) as run:
            _docker(
                ["secret", "create", "EXAMPLE_SECRET", "-"],
                input_value="sensitive-sentinel",
            )

        arguments = run.call_args.args[0]
        self.assertNotIn("sensitive-sentinel", arguments)
        self.assertEqual(
            run.call_args.kwargs["input"],
            b"sensitive-sentinel",
        )

    def test_failed_rotation_retains_named_recovery_secret(self) -> None:
        """Keep a staged proven value when fixed-name replacement fails.

        Returns:
            Nothing.
        """

        profile = SimpleNamespace(stack_name="example")
        identity = SimpleNamespace(docker_secret="EXAMPLE_SECRET")
        successful = subprocess.CompletedProcess(
            args=["docker"],
            returncode=0,
            stdout=b"",
            stderr=b"",
        )
        calls: list[tuple[list[str], str | None]] = []

        def docker_effect(
            arguments: list[str],
            *,
            input_value: str | None = None,
            check: bool = True,
        ) -> subprocess.CompletedProcess[bytes]:
            """Record Docker calls and fail target recreation only.

            Args:
                arguments: Docker CLI arguments excluding the executable.
                input_value: Optional standard-input secret value.
                check: Whether failure should raise.

            Returns:
                Successful fake Docker process for accepted calls.

            Raises:
                KeycloakSecretBridgeError: When recreating the target.
            """

            calls.append((arguments, input_value))
            if arguments[:3] == [
                "secret",
                "create",
                "EXAMPLE_SECRET",
            ]:
                raise KeycloakSecretBridgeError("target create failed")
            return successful

        with (
            patch(
                "keycloak_profile_secret_bridge.docker_secret_exists",
                return_value=True,
            ),
            patch(
                "keycloak_profile_secret_bridge.stack_is_running",
                return_value=False,
            ),
            patch(
                "keycloak_profile_secret_bridge.uuid.uuid4"
            ) as uuid4,
            patch(
                "keycloak_profile_secret_bridge._docker",
                side_effect=docker_effect,
            ),
            self.assertRaisesRegex(
                KeycloakSecretBridgeError,
                "Recovery secret 'keycloak_rotation_0123456789abcdef'",
            ),
        ):
            uuid4.return_value.hex = "0123456789abcdef0123456789abcdef"
            write_docker_secret(
                profile,
                identity,
                "new-sensitive-value",
                replace=True,
            )

        self.assertEqual(
            calls[0],
            (
                [
                    "secret",
                    "create",
                    "keycloak_rotation_0123456789abcdef",
                    "-",
                ],
                "new-sensitive-value",
            ),
        )
        self.assertFalse(
            any(
                arguments[:2] == ["secret", "rm"]
                and "keycloak_rotation_0123456789abcdef" in arguments
                for arguments, _ in calls
            )
        )


if __name__ == "__main__":
    unittest.main()
