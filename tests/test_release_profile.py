"""
Module: test_release_profile.py

Description:
    Verifies strict Swarm production-profile parsing, Felix candidate/legacy
    isolation, production endpoint plausibility, fail-before-operation
    behavior, and atomic guided root `.env` writing.

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
    parse_release_profile,
    render_release_env,
    resolve_profile_path,
    write_release_env,
)
from tests.felix_profile_fixture import (  # noqa: E402
    PRODUCTION_PROFILE,
    production_profile,
)


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
        self.path = self.root / ".env"

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

        selected = values or production_profile()
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

        values = production_profile()
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
        self.assertEqual(summary["publicFieldNames"], list(PRODUCTION_PROFILE))
        self.assertNotIn("https://api.felix-app.fe-wi.com", json.dumps(summary))

    def test_tracked_example_documents_one_valid_public_schema(self) -> None:
        """Accepts the tracked public defaults without using them as runtime.

        Returns:
            None.
        """

        example = Path(__file__).resolve().parents[1] / ".env.example"

        profile = parse_release_profile(example)

        self.assertEqual(profile.values, PRODUCTION_PROFILE)

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

        with self.assertRaisesRegex(
            SwarmReleaseProfileError,
            "Deployment configuration is missing",
        ):
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

        missing = production_profile()
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
                values = production_profile()
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
                values = production_profile()
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

    def test_guided_database_and_proxy_modes_must_be_consistent(self) -> None:
        """Reject impossible local/external database and proxy combinations.

        Returns:
            None.
        """

        cases = (
            (
                production_profile(DB_MODE="external"),
                "External PostgreSQL",
            ),
            (
                production_profile(
                    PROXY_TYPE="none",
                    SSL_MODE="letsencrypt",
                    TRAEFIK_NETWORK="none",
                ),
                "No-proxy mode",
            ),
            (
                production_profile(
                    PGADMIN_ENABLED="true",
                    PGADMIN_DOMAIN="pgadmin.felix-app.fe-wi.com",
                    PGADMIN_EMAIL="admin@fe-wi.com",
                    PGADMIN_REPLICAS="1",
                    PROXY_TYPE="none",
                    TRAEFIK_NETWORK="none",
                ),
                "pgAdmin requires Traefik",
            ),
        )
        for values, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(SwarmReleaseProfileError, expected):
                    self._parse(values)

    def test_required_web_and_disabled_pgadmin_are_enforced(self) -> None:
        """Require WebApp deployment and reject stale disabled pgAdmin fields.

        Returns:
            None.
        """

        self._assert_field_rejected(
            "WEB_ENABLED",
            "false",
            "must be 'true'",
        )
        self._assert_field_rejected(
            "PGADMIN_EMAIL",
            "admin@fe-wi.com",
            "Disabled pgAdmin",
        )

    def test_guided_write_is_public_and_deterministic(self) -> None:
        """Writes only the canonical validated public mapping.

        Returns:
            None.
        """

        profile = write_release_env(self.root, production_profile())
        persisted = profile.path.read_text(encoding="utf-8")

        self.assertEqual(persisted, render_release_env(PRODUCTION_PROFILE))
        self.assertIn("PROFILE_SCHEMA_VERSION=2", persisted)
        self.assertNotIn("PASSWORD", persisted)
        self.assertNotIn("SECRET", persisted)
        self.assertNotIn("TOKEN", persisted)

    def test_guided_write_requires_explicit_overwrite(self) -> None:
        """Protects an existing root `.env` from implicit replacement.

        Returns:
            None.
        """

        destination = self.root / ".env"
        destination.write_text("EXISTING=value\n", encoding="utf-8")

        with self.assertRaisesRegex(
            SwarmReleaseProfileError,
            "pass --force",
        ):
            write_release_env(self.root, production_profile())
        self.assertEqual(destination.read_text(encoding="utf-8"), "EXISTING=value\n")

        write_release_env(self.root, production_profile(), overwrite=True)
        self.assertEqual(
            destination.read_text(encoding="utf-8"),
            render_release_env(PRODUCTION_PROFILE),
        )

    def test_guided_write_accepts_identical_existing_output(self) -> None:
        """Treats deterministic generated public data as idempotent.

        Returns:
            None.
        """

        destination = self.root / ".env"
        destination.write_text(
            render_release_env(PRODUCTION_PROFILE),
            encoding="utf-8",
        )

        write_release_env(self.root, production_profile())

        self.assertEqual(
            destination.read_text(encoding="utf-8"),
            render_release_env(PRODUCTION_PROFILE),
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
