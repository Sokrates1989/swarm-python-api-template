"""
Tests for the Swarm-owned Felix release-orchestration contract.

The suite is dependency-free and verifies public deployment identity without
rendering a stack or reading an operator environment.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


CONTRACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "release_contracts"
    / "felix_swarm_contract.v1.json"
)


class FelixSwarmReleaseContractTests(unittest.TestCase):
    """Verifies candidate isolation, field ownership, and cutover safeguards."""

    def setUp(self) -> None:
        """Load a fresh contract object for each test."""

        self.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_candidate_and_legacy_deployments_are_distinct(self) -> None:
        """Candidate and legacy hosts/realms cannot collapse into one target."""

        candidate = self.contract["candidate"]
        protection = self.contract["legacyProtection"]
        boundary = self.contract["deploymentBoundary"]

        self.assertEqual(candidate["webOrigin"], "https://felix-app.fe-wi.com")
        self.assertEqual(candidate["realm"], "felix-new")
        self.assertEqual(candidate["frontendClientId"], "felix-new-frontend")
        self.assertNotEqual(boundary["candidateHost"], boundary["legacyHost"])
        self.assertNotIn(candidate["realm"], protection["protectedRealms"])

    def test_both_possible_legacy_realms_are_protected(self) -> None:
        """Operator-reported and publicly observed realms remain denylisted."""

        protected_realms = set(self.contract["legacyProtection"]["protectedRealms"])

        self.assertTrue({"felix", "felixappnew"}.issubset(protected_realms))

    def test_required_environment_and_secret_file_fields_are_declared(self) -> None:
        """Public settings and the mounted secret-file boundary remain explicit."""

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

    def test_forwarding_and_image_policy_fail_closed(self) -> None:
        """Old-host forwarding requires approval and mutable tags stay forbidden."""

        boundary = self.contract["deploymentBoundary"]

        self.assertIs(boundary["legacyForwardingRequiresCutoverApproval"], True)
        self.assertIs(boundary["mutableImageTagsAllowed"], False)


if __name__ == "__main__":
    unittest.main()
