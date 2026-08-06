"""
Module: test_keycloak_profile_diagnostics.py

Description:
    Verifies phase-aware, secret-safe Keycloak bootstrap failure guidance and
    the operator handoff to existing production deployment logs.

Dependencies:
    - Python standard library.
    - scripts/keycloak_profile_diagnostics.py.
"""

from __future__ import annotations

import sys
import unittest
from io import StringIO
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from keycloak_profile_diagnostics import (  # noqa: E402
    print_keycloak_failure_diagnostics,
)


class KeycloakProfileDiagnosticsTests(unittest.TestCase):
    """Protect actionable diagnostics without exposing response payloads."""

    def test_http_401_names_phase_refresh_and_log_recovery(self) -> None:
        """Explain an expired/rejected session and where to inspect logs.

        Returns:
            Nothing.
        """

        output = StringIO()
        print_keycloak_failure_diagnostics(
            RuntimeError("request returned HTTP 401"),
            "authenticated Keycloak live-state inspection",
            stream=output,
        )
        rendered = output.getvalue()

        self.assertIn("live-state inspection", rendered)
        self.assertIn("Automatic refresh/retry", rendered)
        self.assertIn("/swarm/administration/keycloak", rendered)
        self.assertIn("docker service logs --since 10m", rendered)
        self.assertNotIn("response body", rendered)

    def test_network_failure_stays_focused_on_reachability(self) -> None:
        """Avoid irrelevant server-log commands for a pure transport failure.

        Returns:
            Nothing.
        """

        output = StringIO()
        print_keycloak_failure_diagnostics(
            RuntimeError("Unable to reach Keycloak."),
            "administrator authentication",
            stream=output,
        )
        rendered = output.getvalue()

        self.assertIn("DNS/TLS reachability", rendered)
        self.assertNotIn("docker service logs", rendered)


if __name__ == "__main__":
    unittest.main()
