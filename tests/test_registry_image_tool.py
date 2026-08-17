"""
Module: test_registry_image_tool.py

Description:
    Verifies stable tag ordering, Docker repository normalization, immutable
    digest comparisons, platform evidence, and cache-summary semantics without
    contacting a registry or Docker daemon.

Dependencies:
    - Python standard library.
    - scripts/registry_image_tool.py.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from registry_image_tool import (  # noqa: E402
    AuditRecord,
    ManifestEvidence,
    RegistryToolError,
    _docker_manifest_fallback,
    audit_records,
    cache_summary,
    inspect_tag,
    normalize_repository,
    stable_tags,
    versioned_test_tags,
    write_cache,
)
from terminal_status import colorize_status_text, print_status  # noqa: E402


class RegistryImageToolTests(unittest.TestCase):
    """Protect the read-only registry evidence model."""

    def test_semantic_status_colors_require_an_interactive_terminal(self) -> None:
        """Color statuses on a TTY while preserving redirected output.

        Returns:
            Nothing.
        """

        interactive_stream = Mock()
        interactive_stream.isatty.return_value = True
        redirected_stream = Mock()
        redirected_stream.isatty.return_value = False

        with patch.dict(
            "terminal_status.os.environ",
            {"TERM": "xterm-256color"},
            clear=True,
        ):
            colored = colorize_status_text(
                "[WARN] review",
                "warning",
                interactive_stream,
            )
            plain = colorize_status_text(
                "[WARN] review",
                "warning",
                redirected_stream,
            )

        self.assertEqual(colored, "\033[33m[WARN] review\033[0m")
        self.assertEqual(plain, "[WARN] review")

    def test_no_color_disables_registry_status_ansi(self) -> None:
        """Honor the standard operator override even on an interactive TTY.

        Returns:
            Nothing.
        """

        interactive_stream = Mock()
        interactive_stream.isatty.return_value = True

        with patch.dict(
            "terminal_status.os.environ",
            {"TERM": "xterm-256color", "NO_COLOR": "1"},
            clear=True,
        ):
            result = colorize_status_text(
                "[ERROR] failed",
                "error",
                interactive_stream,
            )

        self.assertEqual(result, "[ERROR] failed")

    def test_print_status_keeps_redirected_evidence_plain(self) -> None:
        """Write the reusable Python status helper without ANSI to a buffer.

        Returns:
            Nothing.
        """

        output = io.StringIO()

        print_status("[OK] complete", "ok", stream=output)

        self.assertEqual(output.getvalue(), "[OK] complete\n")

    def test_stable_tags_exclude_mutable_and_prerelease_names(self) -> None:
        """Sort only stable SemVer tags and never treat latest as a version.

        Returns:
            Nothing.
        """

        values = [
            "latest",
            "1.0.7",
            "1.0.10",
            "1.1.0-rc.1",
            "v2.0.0",
            "0.9.9",
        ]

        self.assertEqual(stable_tags(values), ["1.0.10", "1.0.7", "0.9.9"])

    def test_versioned_test_tags_exclude_aliases_and_other_prereleases(
        self,
    ) -> None:
        """Sort only exact test-channel tags and exclude latest-test.

        Returns:
            Nothing.
        """

        values = [
            "latest-test",
            "1.0.7-test",
            "1.0.10-test",
            "1.1.0-rc.1",
            "1.0.10",
            "v2.0.0-test",
        ]

        self.assertEqual(
            versioned_test_tags(values),
            ["1.0.10-test", "1.0.7-test"],
        )

    def test_docker_hub_repository_normalization_uses_library_namespace(
        self,
    ) -> None:
        """Normalize official and user repositories for Distribution requests.

        Returns:
            Nothing.
        """

        official = normalize_repository("postgres")
        owned = normalize_repository("sokrates1989/python-api-felix")

        self.assertEqual(official.registry, "docker.io")
        self.assertEqual(official.repository, "library/postgres")
        self.assertEqual(owned.repository, "sokrates1989/python-api-felix")

    @patch("registry_image_tool.subprocess.run")
    def test_buildx_fallback_proves_single_manifest_platform(
        self,
        run_mock,
    ) -> None:
        """Read the image config when single-manifest output omits Platform.

        Args:
            run_mock: Docker Buildx subprocess mock.

        Returns:
            Nothing.
        """

        digest = "sha256:" + "a" * 64
        run_mock.side_effect = [
            Mock(
                returncode=0,
                stdout=(
                    "Name: owner/api:1.1.3-test\n"
                    "MediaType: application/vnd.docker.distribution."
                    "manifest.v2+json\n"
                    f"Digest: {digest}\n"
                ),
                stderr="",
            ),
            Mock(returncode=0, stdout=f"{digest}|linux/amd64\n", stderr=""),
        ]

        evidence = _docker_manifest_fallback("owner/api", "1.1.3-test")

        self.assertEqual(evidence.digest, digest)
        self.assertEqual(evidence.platforms, ("linux/amd64",))
        self.assertEqual(evidence.source, "docker-buildx")
        self.assertIn("--format", run_mock.call_args_list[1].args[0])

    @patch("registry_image_tool.subprocess.run")
    def test_buildx_fallback_rejects_inconsistent_platform_digest(
        self,
        run_mock,
    ) -> None:
        """Reject platform metadata that belongs to another manifest digest.

        Args:
            run_mock: Docker Buildx subprocess mock.

        Returns:
            Nothing.
        """

        digest = "sha256:" + "a" * 64
        other_digest = "sha256:" + "b" * 64
        run_mock.side_effect = [
            Mock(returncode=0, stdout=f"Digest: {digest}\n", stderr=""),
            Mock(
                returncode=0,
                stdout=f"{other_digest}|linux/amd64\n",
                stderr="",
            ),
        ]

        with self.assertRaisesRegex(
            RegistryToolError,
            "inconsistent digest evidence",
        ):
            _docker_manifest_fallback("owner/api", "1.1.3-test")

    @patch("registry_image_tool._docker_manifest_fallback")
    @patch("registry_image_tool.DistributionClient.manifest")
    def test_registry_rate_limit_uses_credential_aware_buildx_fallback(
        self,
        manifest_mock,
        fallback_mock,
    ) -> None:
        """Use Docker credentials when anonymous manifest inspection is limited.

        Args:
            manifest_mock: Anonymous Distribution API manifest mock.
            fallback_mock: Credential-aware Docker Buildx fallback mock.

        Returns:
            Nothing.
        """

        expected = ManifestEvidence(
            "sha256:" + "a" * 64,
            ("linux/amd64",),
            "docker-buildx",
        )
        manifest_mock.side_effect = RegistryToolError("Registry HTTP 429")
        fallback_mock.return_value = expected

        evidence = inspect_tag("owner/api", "1.1.3-test")

        self.assertEqual(evidence, expected)
        fallback_mock.assert_called_once_with("owner/api", "1.1.3-test")

    @patch("registry_image_tool.inspect_tag")
    @patch("registry_image_tool.enumerate_stable_tags")
    def test_application_audit_reports_only_real_higher_registry_version(
        self,
        enumerate_tags_mock,
        inspect_tag_mock,
    ) -> None:
        """Report the highest published stable tag with platform evidence.

        Args:
            enumerate_tags_mock: Registry-tag discovery mock.
            inspect_tag_mock: Exact manifest evidence mock.

        Returns:
            Nothing.
        """

        enumerate_tags_mock.return_value = ["1.0.8", "1.0.7"]
        inspect_tag_mock.return_value = ManifestEvidence(
            "sha256:" + "a" * 64,
            ("linux/amd64",),
            "test",
        )
        record = AuditRecord(
            "api", "Backend API", "application", "owner/api", "1.0.7", ""
        )

        result = audit_records([record], "linux/amd64")[0]

        self.assertEqual(result["status"], "update")
        self.assertEqual(result["highestStable"], "1.0.8")
        self.assertTrue(result["platformVerified"])

    @patch("registry_image_tool.inspect_tag")
    def test_infrastructure_audit_compares_track_tag_with_pinned_digest(
        self,
        inspect_tag_mock,
    ) -> None:
        """Detect a digest refresh without inferring a database major upgrade.

        Args:
            inspect_tag_mock: Exact tracked-tag evidence mock.

        Returns:
            Nothing.
        """

        old_digest = "sha256:" + "a" * 64
        new_digest = "sha256:" + "b" * 64
        inspect_tag_mock.return_value = ManifestEvidence(
            new_digest,
            ("linux/amd64",),
            "test",
        )
        record = AuditRecord(
            "postgres",
            "PostgreSQL",
            "infrastructure",
            "",
            f"postgres@{old_digest}",
            "16-alpine",
        )

        result = audit_records([record], "linux/amd64")[0]

        self.assertEqual(result["status"], "update")
        self.assertEqual(result["track_tag"], "16-alpine")
        self.assertEqual(result["trackedDigest"], new_digest)

    def test_cache_summary_keeps_floor_out_of_freshness_state(self) -> None:
        """Summarize registry evidence without any release-floor comparison.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = Path(temporary_directory) / "audit.json"
            write_cache(
                cache,
                {
                    "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "records": [{"status": "ok"}],
                },
            )
            payload = json.loads(cache.read_text(encoding="utf-8"))
            summary = cache_summary(cache, 24)

        self.assertNotIn("floor", json.dumps(payload).lower())
        self.assertEqual(
            summary,
            "ok|[OK] registry images current; security scan not run",
        )

    @patch("registry_image_tool.inspect_tag")
    @patch("registry_image_tool.enumerate_stable_tags")
    def test_missing_required_platform_never_reports_current(
        self,
        enumerate_tags_mock,
        inspect_tag_mock,
    ) -> None:
        """Treat absent deployment-platform evidence as an unknown state.

        Args:
            enumerate_tags_mock: Registry-tag discovery mock.
            inspect_tag_mock: Exact manifest evidence mock.

        Returns:
            Nothing.
        """

        enumerate_tags_mock.return_value = ["1.0.7"]
        inspect_tag_mock.return_value = ManifestEvidence(
            "sha256:" + "a" * 64,
            ("linux/arm64",),
            "test",
        )
        record = AuditRecord(
            "api", "Backend API", "application", "owner/api", "1.0.7", ""
        )

        result = audit_records([record], "linux/amd64")[0]

        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["platformVerified"])

    def test_stale_security_evidence_is_not_refreshed_by_registry_audit(
        self,
    ) -> None:
        """Keep scanner age independent from a newer registry check.

        Returns:
            Nothing.
        """

        now = dt.datetime.now(dt.timezone.utc)
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = Path(temporary_directory) / "audit.json"
            write_cache(
                cache,
                {
                    "generatedAt": now.isoformat(),
                    "records": [{"status": "ok"}],
                    "security": {
                        "checkedAt": (now - dt.timedelta(days=2)).isoformat(),
                        "status": "ok",
                    },
                },
            )

            summary = cache_summary(cache, 24)

        self.assertEqual(
            summary,
            "warning|[STALE] image security scan needs to be rerun",
        )

    def test_exact_digest_ignore_remains_visible_in_cache_summary(self) -> None:
        """Show snoozed maintenance without reporting an active update.

        Returns:
            Nothing.
        """

        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = Path(temporary_directory) / "audit.json"
            write_cache(
                cache,
                {
                    "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "records": [{"status": "ignored"}],
                },
            )

            summary = cache_summary(cache, 24)

        self.assertEqual(
            summary,
            "off|[IGNORED] 1 infrastructure update reminder(s)",
        )

    def test_security_warning_takes_precedence_over_ignored_refresh(self) -> None:
        """Prevent update snoozes from suppressing vulnerability evidence.

        Returns:
            Nothing.
        """

        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = Path(temporary_directory) / "audit.json"
            write_cache(
                cache,
                {
                    "generatedAt": now,
                    "records": [{"status": "ignored"}],
                    "security": {
                        "checkedAt": now,
                        "status": "warning",
                    },
                },
            )

            summary = cache_summary(cache, 24)

        self.assertEqual(
            summary,
            "warning|[WARN] fixable HIGH/CRITICAL vulnerabilities found",
        )

    def test_security_warning_takes_precedence_over_active_refresh(self) -> None:
        """Keep actionable vulnerability evidence above version freshness.

        Returns:
            Nothing.
        """

        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = Path(temporary_directory) / "audit.json"
            write_cache(
                cache,
                {
                    "generatedAt": now,
                    "records": [{"status": "update"}],
                    "security": {
                        "checkedAt": now,
                        "status": "warning",
                    },
                },
            )

            summary = cache_summary(cache, 24)

        self.assertEqual(
            summary,
            "warning|[WARN] fixable HIGH/CRITICAL vulnerabilities found",
        )


if __name__ == "__main__":
    unittest.main()
