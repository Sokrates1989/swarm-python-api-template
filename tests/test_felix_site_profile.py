"""
Module: test_felix_site_profile.py

Description:
    Verifies the executable Felix Swarm site-profile schema, environment and
    Docker secret selection, immutable image policy, candidate/legacy
    isolation, deterministic rendering, and strict resolved-stack validation.

Dependencies:
    - Python 3.10 or newer standard library.
    - scripts/felix_site_contract.py.
    - scripts/felix_stack_renderer.py.

Usage:
    python -m unittest tests.test_felix_site_profile
"""

from __future__ import annotations

import copy
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from felix_site_contract import (  # noqa: E402
    FelixSiteProfile,
    FelixSiteProfileError,
    load_felix_site_profile,
)
from felix_stack_renderer import (  # noqa: E402
    render_stack,
    validate_rendered_stack,
)
from felix_site_profile import main as site_profile_main  # noqa: E402


_PRODUCTION_VALUES = {
    "PROFILE_SCHEMA_VERSION": "1",
    "APP_ID": "felix",
    "APP_ENVIRONMENT": "production",
    "APP_PROFILE": "felix",
    "BACKEND_APP_ID": "felix",
    "BACKEND_DATA_PROFILE": "postgresql",
    "AUTH_PROVIDER": "keycloak",
    "API_BASE_URL": "https://api.felix-app.fe-wi.com",
    "DOMAIN": "api.felix-app.fe-wi.com",
    "CORS_ORIGINS": "https://felix-app.fe-wi.com",
    "KEYCLOAK_BASE_URL": "https://keycloak.fe-wi.com",
    "KEYCLOAK_ISSUER_URL": "https://keycloak.fe-wi.com/realms/felix-new",
    "KEYCLOAK_REALM": "felix-new",
    "KEYCLOAK_AUDIENCE": "felix-new-backend",
    "KEYCLOAK_FRONTEND_CLIENT_ID": "felix-new-frontend",
    "STACK_NAME": "felix-new",
}


class FelixSiteProfileTests(unittest.TestCase):
    """Exercises strict Felix profile behavior in one isolated repository."""

    def setUp(self) -> None:
        """Create a complete valid candidate profile fixture.

        Returns:
            None.
        """

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.site_config_directory = self.root / "site-configs"
        self.site_config_directory.mkdir()
        source = REPOSITORY_ROOT / "site-configs" / "felix.json"
        self.config = json.loads(source.read_text(encoding="utf-8"))
        self._write_config()
        self._write_production_profile()

    def _write_config(self, config: dict[str, object] | None = None) -> Path:
        """Write one deterministic strict JSON site profile.

        Args:
            config: Optional replacement object; defaults to `self.config`.

        Returns:
            Written `site-configs/felix.json` path.

        Side Effects:
            Replaces the temporary Felix site profile.
        """

        path = self.site_config_directory / "felix.json"
        selected = self.config if config is None else config
        path.write_text(
            json.dumps(selected, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        return path

    def _write_production_profile(
        self,
        values: dict[str, str] | None = None,
    ) -> Path:
        """Write one candidate public `prod.env`.

        Args:
            values: Optional complete replacement mapping.

        Returns:
            Written root `prod.env` path.

        Side Effects:
            Replaces the temporary public production profile.
        """

        selected = values or _PRODUCTION_VALUES
        path = self.root / "prod.env"
        path.write_text(
            "".join(f"{key}={value}\n" for key, value in selected.items()),
            encoding="utf-8",
        )
        return path

    def _load(self) -> FelixSiteProfile:
        """Load the current isolated executable profile.

        Returns:
            Validated `FelixSiteProfile`.
        """

        return load_felix_site_profile(self.root)

    def _enable_capability(self, name: str) -> None:
        """Enable one declared capability and extend executable envKeys.

        Args:
            name: Capability object name (`aiChat` or `webPush`).

        Returns:
            None.

        Side Effects:
            Mutates and writes the temporary site profile.
        """

        capability = self.config["capabilities"][name]
        capability["enabled"] = True
        capability_environment = list(capability["environment"])
        capability_secret_fields = [
            mount["envKey"] for mount in capability["secretMounts"]
        ]
        base_mount_fields = [
            mount["envKey"] for mount in self.config["secretMounts"]
        ]
        prefix_length = len(self.config["envKeys"]) - len(base_mount_fields)
        self.config["envKeys"][prefix_length:prefix_length] = capability_environment
        self.config["envKeys"].extend(capability_secret_fields)
        self._write_config()

    def test_valid_profile_resolves_executable_environment_and_secrets(self) -> None:
        """Resolve exact base envKeys and required Docker secret mounts.

        Returns:
            None.
        """

        profile = self._load()

        self.assertEqual(profile.image_reference, "sokrates1989/python-api-felix:0.1.0")
        self.assertEqual(profile.active_capabilities, ())
        self.assertEqual(
            [mount.name for mount in profile.secret_mounts],
            [
                "FELIX_NEW_DB_PASSWORD",
                "FELIX_NEW_KEYCLOAK_ADMIN_CLIENT_SECRET",
            ],
        )
        self.assertEqual(
            profile.environment["KEYCLOAK_AUDIENCE"],
            "felix-new-backend",
        )
        self.assertEqual(
            set(profile.env_keys),
            set(profile.environment)
            | {mount.env_key for mount in profile.secret_mounts},
        )

    def test_rendered_stack_contains_exact_runtime_and_no_secret_values(self) -> None:
        """Render API, PostgreSQL, Redis, and external secret references.

        Returns:
            None.
        """

        stack = render_stack(self._load())

        self.assertIn('image: "sokrates1989/python-api-felix:0.1.0"', stack)
        self.assertIn('KEYCLOAK_AUDIENCE: "felix-new-backend"', stack)
        self.assertIn(
            'KEYCLOAK_ADMIN_CLIENT_SECRET_FILE: '
            '"/run/secrets/FELIX_NEW_KEYCLOAK_ADMIN_CLIENT_SECRET"',
            stack,
        )
        self.assertIn("api.felix-app.fe-wi.com", stack)
        self.assertIn("entrypoints=http", stack)
        self.assertIn("X-Forwarded-Proto=https", stack)
        self.assertNotIn(".tls=true", stack)
        self.assertNotIn("felix.app.fe-wi.com", stack)
        self.assertNotIn("KEYCLOAK_ADMIN_CLIENT_SECRET:", stack)
        self.assertNotIn("DB_PASSWORD:", stack)
        self.assertNotIn("${", stack)
        self.assertNotIn("XXX_CHANGE", stack)
        self.assertNotIn("###", stack)

    def test_ai_capability_selects_only_its_environment_and_secret(self) -> None:
        """Wire file-backed AI provider input only when explicitly enabled.

        Returns:
            None.
        """

        self._enable_capability("aiChat")
        profile = self._load()
        stack = render_stack(profile)

        self.assertEqual(profile.active_capabilities, ("aiChat",))
        self.assertIn("AI_CHAT_COMPLETIONS_ENDPOINT", profile.env_keys)
        self.assertIn("AI_CHAT_API_KEY_FILE", profile.env_keys)
        self.assertIn("FELIX_NEW_AI_CHAT_API_KEY", stack)
        self.assertNotIn("FELIX_NEW_WEB_PUSH_VAPID_PRIVATE_KEY", stack)

    def test_web_push_capability_selects_both_vapid_files(self) -> None:
        """Wire public/private VAPID files only when dispatch is enabled.

        Returns:
            None.
        """

        self._enable_capability("webPush")
        profile = self._load()
        mount_fields = {mount.env_key for mount in profile.secret_mounts}

        self.assertEqual(profile.active_capabilities, ("webPush",))
        self.assertIn("WEB_PUSH_VAPID_PUBLIC_KEY_FILE", mount_fields)
        self.assertIn("WEB_PUSH_VAPID_PRIVATE_KEY_FILE", mount_fields)
        self.assertEqual(
            profile.environment["WEB_PUSH_DISPATCH_ENABLED"],
            "true",
        )

    def test_env_keys_must_exactly_drive_active_fields(self) -> None:
        """Reject missing, reordered, duplicate, and commentary-only envKeys.

        Returns:
            None.
        """

        self.config["envKeys"].remove("AUTH_PROVIDER")
        self._write_config()

        with self.assertRaisesRegex(FelixSiteProfileError, "envKeys must exactly"):
            self._load()

    def test_required_secret_names_must_match_mounts(self) -> None:
        """Reject required Docker secrets not driven by a file mount.

        Returns:
            None.
        """

        self.config["secrets"][0] = "FELIX_NEW_OTHER_PASSWORD"
        self._write_config()

        with self.assertRaisesRegex(FelixSiteProfileError, "secrets must exactly"):
            self._load()

    def test_mutable_api_or_service_images_are_rejected(self) -> None:
        """Reject latest API tags and non-digest infrastructure images.

        Returns:
            None.
        """

        mutable_api = copy.deepcopy(self.config)
        mutable_api["image"]["defaultVersion"] = "latest"
        mutable_api["environment"]["IMAGE_TAG"] = "latest"
        self._write_config(mutable_api)
        with self.assertRaisesRegex(FelixSiteProfileError, "semantic version"):
            self._load()

        mutable_service = copy.deepcopy(self.config)
        mutable_service["services"]["redisImage"] = "redis:7-alpine"
        self._write_config(mutable_service)
        with self.assertRaisesRegex(FelixSiteProfileError, "pinned by SHA-256"):
            self._load()

    def test_candidate_profile_rejects_audience_and_legacy_drift(self) -> None:
        """Reject a mismatched backend client or protected legacy origin.

        Returns:
            None.
        """

        wrong_audience = dict(_PRODUCTION_VALUES)
        wrong_audience["KEYCLOAK_AUDIENCE"] = "felix-api"
        self._write_production_profile(wrong_audience)
        with self.assertRaisesRegex(FelixSiteProfileError, "KEYCLOAK_AUDIENCE"):
            self._load()

        self._write_production_profile()
        self.config["cors"]["origins"] = ["https://felix.app.fe-wi.com"]
        self._write_config()
        with self.assertRaisesRegex(FelixSiteProfileError, "cors.origins"):
            self._load()

    def test_direct_secret_environment_field_is_rejected(self) -> None:
        """Reject plaintext secret-bearing environment declarations.

        Returns:
            None.
        """

        self.config["environment"]["DB_PASSWORD"] = "not-allowed"
        self.config["envKeys"].insert(-2, "DB_PASSWORD")
        self._write_config()

        with self.assertRaisesRegex(FelixSiteProfileError, "Direct secret"):
            self._load()

    def test_unresolved_markers_are_rejected_before_render(self) -> None:
        """Reject placeholder values in executable environment declarations.

        Returns:
            None.
        """

        self.config["environment"]["LOG_LEVEL"] = "${LOG_LEVEL}"
        self._write_config()

        with self.assertRaisesRegex(FelixSiteProfileError, "placeholder"):
            self._load()

    def test_rendered_stack_validation_rejects_marker_and_direct_secret(self) -> None:
        """Reject unsafe mutation of an otherwise valid rendered stack.

        Returns:
            None.
        """

        profile = self._load()
        stack = render_stack(profile)
        with self.assertRaisesRegex(FelixSiteProfileError, "unresolved marker"):
            validate_rendered_stack(stack + "\n# ${UNRESOLVED}\n", profile)
        with self.assertRaisesRegex(FelixSiteProfileError, "direct secret"):
            validate_rendered_stack(stack + "\n      DB_PASSWORD: \"leak\"\n", profile)
        with self.assertRaisesRegex(FelixSiteProfileError, "HTTPS URL|local endpoint"):
            validate_rendered_stack(
                stack + '\n      KEYCLOAK_SERVER_URL: "http://localhost:8080"\n',
                profile,
            )

    def test_duplicate_json_keys_fail_closed(self) -> None:
        """Reject duplicate keys before any profile operation may continue.

        Returns:
            None.
        """

        path = self.site_config_directory / "felix.json"
        path.write_text('{"version":"4.0","version":"3.0"}\n', encoding="utf-8")

        with self.assertRaisesRegex(FelixSiteProfileError, "Duplicate JSON key"):
            self._load()

    def test_cli_renders_and_revalidates_exact_root_artifact(self) -> None:
        """Exercise the non-deploying CLI render and validate-stack operations.

        Returns:
            None.

        Side Effects:
            Writes one temporary root `swarm-stack.yml`.
        """

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            render_result = site_profile_main(
                ["--root", str(self.root), "render"]
            )
            validate_result = site_profile_main(
                ["--root", str(self.root), "validate-stack"]
            )

        self.assertEqual(render_result, 0)
        self.assertEqual(validate_result, 0)
        self.assertEqual(
            (self.root / "swarm-stack.yml").read_text(encoding="utf-8"),
            render_stack(self._load()),
        )

    @unittest.skipUnless(
        os.environ.get("RUN_DOCKER_COMPOSE_TESTS") == "1",
        "set RUN_DOCKER_COMPOSE_TESTS=1 for the host integration gate",
    )
    def test_rendered_stack_passes_docker_compose_config(self) -> None:
        """Require Docker Compose to accept the exact resolved stack.

        Returns:
            None.

        Side Effects:
            Starts a read-only Docker Compose configuration subprocess against
            one temporary, secret-free rendered stack.
        """

        stack_path = self.root / "swarm-stack.yml"
        stack_path.write_text(render_stack(self._load()), encoding="utf-8")
        completed = subprocess.run(
            ["docker", "compose", "-f", str(stack_path), "config", "--quiet"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr or completed.stdout,
        )


if __name__ == "__main__":
    unittest.main()
