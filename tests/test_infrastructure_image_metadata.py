"""
Module: test_infrastructure_image_metadata.py

Description:
    Verifies product-version extraction from OCI configuration payloads without
    contacting a registry.

Dependencies:
    - Python standard library.
    - scripts/infrastructure_image_metadata.py.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from infrastructure_image_metadata import (  # noqa: E402
    release_version_from_config,
)


class InfrastructureImageMetadataTests(unittest.TestCase):
    """Protect fallback version extraction for official infrastructure images."""

    def test_postgres_package_metadata_yields_product_version(self) -> None:
        """Trim distribution packaging text from the PostgreSQL release.

        Returns:
            Nothing.
        """

        configuration = {
            "config": {
                "Env": ["PG_MAJOR=16", "PG_VERSION=16.10-1.pgdg120+1"]
            }
        }

        version = release_version_from_config(configuration, "postgres")

        self.assertEqual(version, "16.10")

    def test_oci_version_label_is_a_generic_fallback(self) -> None:
        """Use a standard OCI release label when a product field is absent.

        Returns:
            Nothing.
        """

        configuration = {
            "config": {"Labels": {"org.opencontainers.image.version": "v9.17"}}
        }

        version = release_version_from_config(configuration, "pgadmin")

        self.assertEqual(version, "9.17")


if __name__ == "__main__":
    unittest.main()
