"""
Module: test_infrastructure_image_tool.py

Description:
    Verifies infrastructure record resolution and machine-readable ignored
    candidate output without contacting a registry or Docker daemon.

Dependencies:
    - Python standard library.
    - scripts/infrastructure_image_tool.py.
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from infrastructure_image_tool import (  # noqa: E402
    InfrastructureRecord,
    ResolvedInfrastructure,
    main,
    resolve_record,
)
from registry_image_tool import ManifestEvidence, write_cache  # noqa: E402


RECORD = (
    "postgres|PostgreSQL|postgres|POSTGRES_IMAGE|"
    "postgres@sha256:{digest}|16-alpine|database|"
    "https://www.postgresql.org/docs/current/upgrading.html"
)


class InfrastructureImageToolTests(unittest.TestCase):
    """Protect immutable target resolution and reminder integration."""

    @patch("infrastructure_image_tool.inspect_tag")
    def test_resolve_record_compares_current_and_track_digest(
        self, inspect_tag_mock
    ) -> None:
        """Classify a different track digest as a compatible refresh.

        Args:
            inspect_tag_mock: Exact registry manifest resolver mock.

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

        resolved = resolve_record(
            RECORD.format(digest="a" * 64),
            "linux/amd64",
        )

        self.assertEqual(resolved.current_digest, old_digest)
        self.assertEqual(resolved.target_digest, new_digest)
        self.assertEqual(resolved.status, "update")
        self.assertEqual(resolved.target_reference, f"postgres@{new_digest}")

    @patch("infrastructure_image_tool.resolve_record")
    def test_candidates_mark_only_the_matching_ignored_digest(
        self, resolve_record_mock
    ) -> None:
        """Expose a matching cache snooze as ignored to the Bash menu.

        Args:
            resolve_record_mock: Current/target evidence resolver mock.

        Returns:
            Nothing.
        """

        digest = "sha256:" + "c" * 64
        record = InfrastructureRecord(
            "postgres",
            "PostgreSQL",
            "postgres",
            "POSTGRES_IMAGE",
            "postgres@sha256:" + "a" * 64,
            "16-alpine",
            "database",
            "https://www.postgresql.org/docs/current/upgrading.html",
        )
        resolve_record_mock.return_value = ResolvedInfrastructure(
            record,
            "postgres",
            "sha256:" + "a" * 64,
            digest,
            f"postgres@{digest}",
            "update",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            cache = Path(temporary_directory) / "audit.json"
            write_cache(
                cache,
                {
                    "ignoredInfrastructureUpdates": {
                        "postgres": {"digest": digest, "reason": "deferred"}
                    }
                },
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = main(
                    [
                        "candidates",
                        "--record",
                        RECORD.format(digest="a" * 64),
                        "--cache",
                        str(cache),
                    ]
                )

        self.assertEqual(status, 0)
        self.assertEqual(output.getvalue().strip().split("|")[-2], "ignored")


if __name__ == "__main__":
    unittest.main()
