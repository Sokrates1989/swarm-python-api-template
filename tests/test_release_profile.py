"""
Module: test_release_profile.py

Description:
    Verifies strict Swarm production-profile parsing, Felix candidate/legacy
    isolation, production endpoint plausibility, fail-before-operation
    behavior, and public-only compatibility materialization.

Dependencies:
    - Python 3.10 or newer standard library.
    - scripts/release_profile.py.

Usage:
    python -m unittest tests.test_release_profile
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from release_profile import (  # noqa: E402
    SwarmReleaseProfile,
    SwarmReleaseProfileError,
    execute_with_validated_profile,
    materialize_compatibility_env,
    parse_release_profile,
    render_compatibility_env,
    resolve_profile_path,
)


_PRODUCTION_VALUES = {
    "PROFILE_SCHEMA_VERSION": "1",
    "APP_ID": "felix",
    "APP_ENVIRONMENT": "production",
    "APP_PROFILE": "felix",
    "BACKEND_APP_ID": "felix",
    "BACKEND_DATA_PROFILE": "postgresql",
    "AUTH_PROVIDER": "keycloak",
    "API_BASE_URL": "https://api.fe-wi.com",
    "DOMAIN": "api.fe-wi.com",
    "CORS_ORIGINS": "https://felix-app.fe-wi.com",
    "KEYCLOAK_BASE_URL": "https://keycloak.fe-wi.com",
    "KEYCLOAK_ISSUER_URL": "https://keycloak.fe-wi.com/realms/felix-new",
    "KEYCLOAK_REALM": "felix-new",
    "KEYCLOAK_AUDIENCE": "felix-new-backend",
    "KEYCLOAK_FRONTEND_CLIENT_ID": "felix-new-frontend",
    "STACK_NAME": "felix-new",
}


class SwarmReleaseProfileTest(unittest.TestCase):
    """Exercises candidate-production profile behavior in a temporary clone."""

    def setUp(self) -> None:
        """Creates an isolated Swarm repository root.

        Returns:
            None.
        """

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.path = self.root / "prod.env"

    def _write_profile(
        self,
        values: dict[str, str] | None = None,
        *,
        prefix: str = "",
        suffix: str = "",
    ) -> Path:
        """Writes one deterministic profile fixture.

        Args:
            values: Optional mapping replacing the valid fixture.
            prefix: Optional raw text before assignments.
            suffix: Optional raw text after assignments.

        Returns:
            Written root profile path.
        """

        selected = values or dict(_PRODUCTION_VALUES)
        content = prefix + "".join(
            f"{key}={value}\n" for key, value in selected.items()
        ) + suffix
        self.path.write_text(content, encoding="utf-8")
        return self.path

    def _parse(
        self,
        values: dict[str, str] | None = None,
    ) -> SwarmReleaseProfile:
        """Writes and parses one production fixture.

        Args:
            values: Optional mapping replacing the valid fixture.

        Returns:
            Validated immutable Swarm profile.
        """

        return parse_release_profile(self._write_profile(values))

    def _assert_field_rejected(self, key: str, value: str, message: str) -> None:
        """Requires one mutated field to fail with a focused diagnostic.

        Args:
            key: Fixture key to replace.
            value: Invalid replacement value.
            message: Expected diagnostic fragment.

        Returns:
            None.
        """

        values = dict(_PRODUCTION_VALUES)
        values[key] = value
        with self.assertRaisesRegex(SwarmReleaseProfileError, message):
            self._parse(values)

    def test_valid_profile_has_deterministic_sanitized_evidence(self) -> None:
        """Accepts the approved candidate without retaining public values.

        Returns:
            None.
        """

        profile = self._parse()
        summary = profile.safe_summary()

        self.assertEqual(summary["appId"], "felix")
        self.assertEqual(summary["environment"], "production")
        self.assertRegex(str(summary["profileFingerprint"]), r"^[0-9a-f]{64}$")
        self.assertEqual(summary["publicFieldNames"], list(_PRODUCTION_VALUES))
        self.assertNotIn("https://api.fe-wi.com", json.dumps(summary))

    def test_tracked_example_fails_closed_until_operator_input_exists(self) -> None:
        """Rejects the committed `.invalid` API placeholder.

        Returns:
            None.
        """

        example = Path(__file__).resolve().parents[1] / "prod.env.example"

        with self.assertRaisesRegex(SwarmReleaseProfileError, "placeholder"):
            parse_release_profile(example)

    def test_missing_profile_prevents_operation_callback(self) -> None:
        """Does not invoke downstream deployment work without a profile.

        Returns:
            None.
        """

        calls: list[str] = []

        def record(profile: SwarmReleaseProfile) -> int:
            """Records an operation that validation must prevent.

            Args:
                profile: Validated profile that must not be received.

            Returns:
                Zero when invoked.
            """

            calls.append(profile.fingerprint)
            return 0

        with self.assertRaisesRegex(SwarmReleaseProfileError, "Profile is missing"):
            execute_with_validated_profile(self.root, record)
        self.assertEqual(calls, [])

    def test_valid_profile_invokes_operation_once(self) -> None:
        """Passes exactly one validated profile to downstream work.

        Returns:
            None.
        """

        self._write_profile()
        calls: list[str] = []

        def record(profile: SwarmReleaseProfile) -> int:
            """Records a validated operation call.

            Args:
                profile: Validated public candidate profile.

            Returns:
                Sentinel operation result.
            """

            calls.append(profile.fingerprint)
            return 9

        result = execute_with_validated_profile(self.root, record)

        self.assertEqual(result, 9)
        self.assertEqual(len(calls), 1)

    def test_parser_rejects_malformed_duplicate_unknown_and_secret_keys(self) -> None:
        """Rejects shell syntax, duplicate keys, and schema escape attempts.

        Returns:
            None.
        """

        cases = (
            ("export APP_ID=felix\n", "", "expected one unquoted"),
            ("", "APP_ID=felix\n", "duplicate key"),
            ("", "UNEXPECTED=value\n", "unknown key"),
            ("", "KEYCLOAK_CLIENT_SECRET=value\n", "secret-looking"),
        )
        for prefix, suffix, expected in cases:
            with self.subTest(expected=expected):
                path = self._write_profile(prefix=prefix, suffix=suffix)
                with self.assertRaisesRegex(SwarmReleaseProfileError, expected):
                    parse_release_profile(path)

    def test_parser_rejects_missing_and_cross_app_fields(self) -> None:
        """Rejects incomplete and non-Felix runtime identities.

        Returns:
            None.
        """

        missing = dict(_PRODUCTION_VALUES)
        del missing["AUTH_PROVIDER"]
        with self.assertRaisesRegex(SwarmReleaseProfileError, "missing required"):
            self._parse(missing)

        self._assert_field_rejected("APP_ID", "other", "must equal 'felix'")
        self._assert_field_rejected(
            "APP_PROFILE",
            "demo_app",
            "must equal 'felix'",
        )
        self._assert_field_rejected(
            "BACKEND_APP_ID",
            "demo_app",
            "must equal 'felix'",
        )

    def test_production_rejects_unsafe_api_endpoints(self) -> None:
        """Rejects local, private, placeholder, and `/api`-prefixed URLs.

        Returns:
            None.
        """

        cases = (
            ("http://api.fe-wi.com", "absolute HTTPS"),
            ("https://localhost", "local or private"),
            ("https://10.0.2.2", "local or private"),
            ("https://10.2.3.4", "local or private"),
            ("https://169.254.1.2", "local or private"),
            ("https://*.fe-wi.com", "wildcard"),
            ("https://user:pass@api.fe-wi.com", "credentials"),
            ("https://api.fe-wi.com?mode=prod", "query or fragment"),
            ("https://api.fe-wi.com/api", "redundant /api"),
            ("https://api.example.invalid", "placeholder"),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                values = dict(_PRODUCTION_VALUES)
                values["API_BASE_URL"] = value
                parsed = value.split("://")[-1].split("/", 1)[0]
                values["DOMAIN"] = parsed
                with self.assertRaisesRegex(SwarmReleaseProfileError, expected):
                    self._parse(values)

    def test_api_domain_and_keycloak_issuer_must_agree(self) -> None:
        """Rejects API-host and exact realm-issuer drift.

        Returns:
            None.
        """

        self._assert_field_rejected(
            "DOMAIN",
            "other.fe-wi.com",
            "must match",
        )
        self._assert_field_rejected(
            "KEYCLOAK_ISSUER_URL",
            "https://keycloak.fe-wi.com/realms/other",
            "declared realm",
        )

    def test_candidate_rejects_legacy_origin_realm_client_and_stack(self) -> None:
        """Protects both possible legacy realm names and old public identities.

        Returns:
            None.
        """

        cases = (
            ("CORS_ORIGINS", "https://felix.app.fe-wi.com"),
            ("KEYCLOAK_REALM", "felix"),
            ("KEYCLOAK_REALM", "felixappnew"),
            ("KEYCLOAK_FRONTEND_CLIENT_ID", "felixappnew-frontend"),
            ("STACK_NAME", "felix"),
        )
        for key, value in cases:
            with self.subTest(key=key, value=value):
                values = dict(_PRODUCTION_VALUES)
                values[key] = value
                if key == "KEYCLOAK_REALM":
                    values["KEYCLOAK_ISSUER_URL"] = (
                        f"https://keycloak.fe-wi.com/realms/{value}"
                    )
                with self.assertRaisesRegex(
                    SwarmReleaseProfileError,
                    "legacy",
                ):
                    self._parse(values)

    def test_compatibility_materialization_is_public_and_deterministic(self) -> None:
        """Writes only the canonical validated public mapping.

        Returns:
            None.
        """

        profile = self._parse()
        destination = self.root / ".env"

        materialize_compatibility_env(profile, destination)
        persisted = destination.read_text(encoding="utf-8")

        self.assertEqual(persisted, render_compatibility_env(profile))
        self.assertIn("PROFILE_SCHEMA_VERSION=1", persisted)
        self.assertNotIn("PASSWORD", persisted)
        self.assertNotIn("SECRET", persisted)
        self.assertNotIn("TOKEN", persisted)

    def test_materialization_requires_explicit_overwrite(self) -> None:
        """Protects an existing root `.env` from implicit replacement.

        Returns:
            None.
        """

        profile = self._parse()
        destination = self.root / ".env"
        destination.write_text("EXISTING=value\n", encoding="utf-8")

        with self.assertRaisesRegex(
            SwarmReleaseProfileError,
            "pass --force",
        ):
            materialize_compatibility_env(profile, destination)
        self.assertEqual(destination.read_text(encoding="utf-8"), "EXISTING=value\n")

        materialize_compatibility_env(profile, destination, overwrite=True)
        self.assertEqual(
            destination.read_text(encoding="utf-8"),
            render_compatibility_env(profile),
        )

    def test_materialization_accepts_identical_existing_output(self) -> None:
        """Treats deterministic generated compatibility data as idempotent.

        Returns:
            None.
        """

        profile = self._parse()
        destination = self.root / ".env"
        destination.write_text(render_compatibility_env(profile), encoding="utf-8")

        materialize_compatibility_env(profile, destination)

        self.assertEqual(
            destination.read_text(encoding="utf-8"),
            render_compatibility_env(profile),
        )

    def test_profile_override_cannot_escape_repository_root(self) -> None:
        """Rejects arbitrary alternate production-profile paths.

        Returns:
            None.
        """

        with self.assertRaisesRegex(
            SwarmReleaseProfileError,
            "repository-owned path",
        ):
            resolve_profile_path(self.root, self.root / "other.env")


if __name__ == "__main__":
    unittest.main()
