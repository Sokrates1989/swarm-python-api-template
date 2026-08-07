"""
Module: test_infrastructure_image_policy.py

Description:
    Verifies compatibility-track tag selection and exact-target reminder
    snoozes without contacting Docker or an external registry.

Dependencies:
    - Python standard library.
    - scripts/infrastructure_image_policy.py.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from infrastructure_image_policy import (  # noqa: E402
    apply_update_ignores,
    clear_exact_digest_ignore,
    compatible_release_tags,
    parse_version_tag,
    store_exact_digest_ignore,
)


class InfrastructureImagePolicyTests(unittest.TestCase):
    """Protect reusable infrastructure compatibility and ignore semantics."""

    def test_postgres_track_rejects_major_and_image_family_drift(self) -> None:
        """Keep a PostgreSQL Alpine major track inside both boundaries.

        Returns:
            Nothing.
        """

        tags = compatible_release_tags(
            (
                "17.1-alpine",
                "16.14-bookworm",
                "16.14-alpine",
                "16.14-alpine3.24",
                "16.13-alpine",
                "16beta2-alpine",
                "16-alpine",
            ),
            "16-alpine",
        )

        self.assertEqual(
            tags,
            ["16.14-alpine", "16.14-alpine3.24", "16.13-alpine"],
        )

    def test_redis_track_lists_minor_and_patch_releases_only(self) -> None:
        """Treat Redis 7 minor/patch releases as compatible track options.

        Returns:
            Nothing.
        """

        tags = compatible_release_tags(
            ("8.0.1-alpine", "7.4.10-alpine", "7.4-alpine", "7.2.14-alpine"),
            "7-alpine",
        )

        self.assertEqual(
            tags,
            ["7.4.10-alpine", "7.4-alpine", "7.2.14-alpine"],
        )

    def test_latest_track_accepts_only_stable_unsuffixed_versions(self) -> None:
        """Exclude prerelease and OS-variant tags from a stateless latest track.

        Returns:
            Nothing.
        """

        tags = compatible_release_tags(
            ("latest", "10.1", "9.17", "9.17-alpine", "9.18-rc1"),
            "latest",
        )

        self.assertEqual(tags, ["10.1", "9.17"])
        self.assertIsNone(parse_version_tag("9.18-rc1"))

    def test_ignore_applies_only_to_the_exact_observed_target(self) -> None:
        """Expire a snooze automatically when the registry target changes.

        Returns:
            Nothing.
        """

        first_digest = "sha256:" + "a" * 64
        next_digest = "sha256:" + "b" * 64
        ignored = {
            "postgres": {
                "digest": first_digest,
                "reason": "maintenance window",
            }
        }
        result = {
            "identifier": "postgres",
            "kind": "infrastructure",
            "status": "update",
            "trackedDigest": first_digest,
        }

        snoozed, active = apply_update_ignores([result], ignored)
        result["trackedDigest"] = next_digest
        refreshed, expired = apply_update_ignores([result], ignored)

        self.assertEqual(snoozed[0]["status"], "ignored")
        self.assertEqual(active, ignored)
        self.assertEqual(refreshed[0]["status"], "update")
        self.assertEqual(expired, {})

    def test_store_and_clear_ignore_preserve_public_reason(self) -> None:
        """Persist and remove one validated non-secret reminder reason.

        Returns:
            Nothing.
        """

        payload: dict[str, object] = {}
        digest = "sha256:" + "c" * 64

        store_exact_digest_ignore(
            payload,
            "redis",
            "Redis",
            digest,
            "  wait   for maintenance  ",
        )
        stored = payload["ignoredInfrastructureUpdates"]["redis"]
        removed = clear_exact_digest_ignore(payload, "redis")

        self.assertEqual(stored["reason"], "wait for maintenance")
        self.assertTrue(removed)
        self.assertEqual(payload["ignoredInfrastructureUpdates"], {})


if __name__ == "__main__":
    unittest.main()
