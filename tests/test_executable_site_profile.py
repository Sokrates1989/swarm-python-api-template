"""
Module: test_executable_site_profile.py

Description:
    Exercises the reusable schema-5 site-profile configuration, stack renderer,
    optional WebApp/database services, and Keycloak identity adapter. A renamed
    synthetic application proves the implementation has no Felix dependency.

Dependencies:
    - Python standard library.
    - scripts/executable_profile.py.
    - scripts/executable_profile_environment.py.
    - scripts/executable_stack_renderer.py.
    - scripts/keycloak_profile_bootstrap.py.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

from executable_profile import (  # noqa: E402
    ExecutableProfileError,
    load_executable_profile,
)
from executable_profile_environment import (  # noqa: E402
    load_config_defaults,
    write_deployment_env,
)
from executable_stack_renderer import (  # noqa: E402
    render_stack,
    validate_rendered_stack,
)
from keycloak_profile_bootstrap import (  # noqa: E402
    _backend_payload,
    _frontend_payload,
    load_keycloak_identity,
)


def _rename_profile_value(value: object) -> object:
    """Recursively rename Felix fixture identity to a synthetic application.

    Args:
        value: Arbitrary JSON-compatible value.

    Returns:
        Structurally equivalent value with identity strings renamed.
    """

    if isinstance(value, dict):
        return {
            str(key): _rename_profile_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rename_profile_value(item) for item in value]
    if isinstance(value, str):
        return (
            value.replace("FELIX", "AURORA")
            .replace("Felix", "Aurora")
            .replace("felix", "aurora")
        )
    return value


class ExecutableSiteProfileTests(unittest.TestCase):
    """Verify profile-only application identity and deterministic rendering."""

    def setUp(self) -> None:
        """Create an isolated deployment root and load the tracked fixture.

        Returns:
            Nothing.
        """

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config_directory = self.root / "site-configs"
        self.config_directory.mkdir()
        self.felix_config = json.loads(
            (REPOSITORY_ROOT / "site-configs" / "felix.json").read_text(
                encoding="utf-8"
            )
        )

    def tearDown(self) -> None:
        """Remove the isolated deployment root.

        Returns:
            Nothing.
        """

        self.temporary.cleanup()

    def _write_config(
        self,
        config_id: str,
        profile: dict[str, object],
    ) -> Path:
        """Write one JSON fixture to the isolated site-config directory.

        Args:
            config_id: Site-config filename stem.
            profile: JSON-compatible profile object.

        Returns:
            Written profile path.
        """

        path = self.config_directory / f"{config_id}.json"
        path.write_text(
            json.dumps(profile, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def _configure(
        self,
        config_id: str,
        profile: dict[str, object],
        overrides: dict[str, str] | None = None,
    ):
        """Write and load one fully validated executable deployment.

        Args:
            config_id: Site-config filename stem.
            profile: JSON-compatible profile object.
            overrides: Optional operator-owned deployment overrides.

        Returns:
            Loaded executable profile.
        """

        self._write_config(config_id, profile)
        write_deployment_env(
            self.root,
            config_id,
            overrides or {},
            force=True,
        )
        return load_executable_profile(self.root)

    def test_felix_values_are_data_and_render_one_full_stack(self) -> None:
        """Render Felix WebApp and backend solely from its tracked profile.

        Returns:
            Nothing.
        """

        profile = self._configure("felix", self.felix_config)
        stack = render_stack(profile)

        self.assertEqual(profile.stack_name, "felix")
        self.assertEqual(
            profile.image_reference,
            "sokrates1989/python-api-felix:0.1.1",
        )
        self.assertEqual(
            profile.web_image_reference,
            "sokrates1989/flutter-felix-web:1.0.5",
        )
        self.assertIn("\n  web:\n", stack)
        self.assertIn("\n  api:\n", stack)
        self.assertIn("\n  redis:\n", stack)
        self.assertIn("\n  postgres:\n", stack)
        self.assertIn("felix-app.fe-wi.com", stack)
        self.assertIn("api.felix-app.fe-wi.com", stack)
        self.assertNotIn("felix.app.fe-wi.com", stack)
        validate_rendered_stack(stack, profile)

    def test_renamed_application_uses_identical_setup_and_renderer(self) -> None:
        """Prove all application identity comes from a renamed site config.

        Returns:
            Nothing.
        """

        synthetic = _rename_profile_value(copy.deepcopy(self.felix_config))
        self.assertIsInstance(synthetic, dict)
        profile = self._configure("aurora", synthetic)
        stack = render_stack(profile)
        identity = load_keycloak_identity(profile)

        self.assertEqual(profile.config_id, "aurora")
        self.assertEqual(profile.stack_name, "aurora")
        self.assertEqual(profile.deployment["APP_ID"], "aurora")
        self.assertEqual(
            profile.image_reference,
            "sokrates1989/python-api-aurora:0.1.1",
        )
        self.assertEqual(
            profile.web_image_reference,
            "sokrates1989/flutter-aurora-web:1.0.5",
        )
        self.assertEqual(identity.realm, "aurora-new")
        self.assertEqual(identity.frontend_client_id, "aurora-new-frontend")
        self.assertEqual(identity.backend_client_id, "aurora-new-backend")
        self.assertEqual(identity.docker_secret, "AURORA_KEYCLOAK_ADMIN_CLIENT_SECRET")
        self.assertIn("aurora-app.fe-wi.com", stack)
        self.assertIn("AURORA_DB_PASSWORD", stack)
        self.assertNotIn("felix", stack.lower())

    def test_web_service_is_optional_profile_data(self) -> None:
        """Omit WebApp when services.web is false without changing code.

        Returns:
            Nothing.
        """

        synthetic = _rename_profile_value(copy.deepcopy(self.felix_config))
        self.assertIsInstance(synthetic, dict)
        services = synthetic["services"]
        routing = synthetic["routing"]
        self.assertIsInstance(services, dict)
        self.assertIsInstance(routing, dict)
        services["web"] = False
        synthetic.pop("web")
        for key in (
            "webContainerPort",
            "webBaseUrl",
            "webDomain",
            "webHealthPath",
            "webPublishedPort",
        ):
            routing.pop(key)
        profile = self._configure("aurora", synthetic)
        stack = render_stack(profile)

        self.assertEqual(profile.web_image_reference, "")
        self.assertNotIn("\n  web:\n", stack)
        self.assertIn("\n  api:\n", stack)

    def test_external_database_omits_postgres_service(self) -> None:
        """Use profile-allowed external PostgreSQL without a code branch.

        Returns:
            Nothing.
        """

        profile = self._configure(
            "felix",
            self.felix_config,
            {
                "DB_MODE": "external",
                "DB_HOST": "postgres.internal",
                "DB_PORT": "5432",
            },
        )
        stack = render_stack(profile)

        self.assertNotIn("\n  postgres:\n", stack)
        self.assertIn('DB_HOST: "postgres.internal"', stack)

    def test_pgadmin_is_enabled_by_environment_and_profile_declaration(self) -> None:
        """Render optional pgAdmin with its profile-declared image and secret.

        Returns:
            Nothing.
        """

        profile = self._configure(
            "felix",
            self.felix_config,
            {
                "PGADMIN_ENABLED": "true",
                "PGADMIN_REPLICAS": "1",
            },
        )
        stack = render_stack(profile)

        self.assertIn("\n  pgadmin:\n", stack)
        self.assertIn("FELIX_PGADMIN_PASSWORD", stack)
        self.assertIn("pgadmin.felix-app.fe-wi.com", stack)

    def test_direct_ports_include_optional_pgadmin(self) -> None:
        """Publish every public service when Traefik is disabled.

        Returns:
            Nothing.
        """

        profile = self._configure(
            "felix",
            self.felix_config,
            {
                "PROXY_TYPE": "none",
                "SSL_MODE": "",
                "TRAEFIK_NETWORK": "",
                "TRAEFIK_CONSTRAINT_LABEL": "",
                "PGADMIN_ENABLED": "true",
                "PGADMIN_REPLICAS": "1",
                "PGADMIN_PUBLISHED_PORT": "5054",
            },
        )
        stack = render_stack(profile)

        self.assertIn("published: 8083", stack)
        self.assertIn("published: 8084", stack)
        self.assertIn("published: 5054", stack)

    def test_letsencrypt_resolver_is_operator_configuration(self) -> None:
        """Render the configured Traefik resolver without a hard-coded name.

        Returns:
            Nothing.
        """

        profile = self._configure(
            "felix",
            self.felix_config,
            {
                "SSL_MODE": "letsencrypt",
                "TRAEFIK_CERT_RESOLVER": "production-acme",
            },
        )
        stack = render_stack(profile)

        self.assertIn("tls.certresolver=production-acme", stack)
        self.assertNotIn("tls.certresolver=le\"", stack)

    def test_traefik_provider_label_is_independent_from_overlay(self) -> None:
        """Render distinct provider-selection and network-membership values.

        Returns:
            Nothing.
        """

        profile = self._configure(
            "felix",
            self.felix_config,
            {
                "TRAEFIK_NETWORK": "shared-edge-overlay",
                "TRAEFIK_CONSTRAINT_LABEL": "traefik-public-provider",
            },
        )
        stack = render_stack(profile)

        self.assertIn(
            "traefik.constraint-label=traefik-public-provider",
            stack,
        )
        self.assertIn(
            "traefik.docker.network=shared-edge-overlay",
            stack,
        )
        self.assertIn('"shared-edge-overlay":', stack)
        self.assertNotIn(
            "traefik.constraint-label=shared-edge-overlay",
            stack,
        )

    def test_traefik_provider_label_rejects_unsafe_values(self) -> None:
        """Reject provider labels that cannot safely enter Compose metadata.

        Returns:
            Nothing.
        """

        self._write_config("felix", self.felix_config)
        with self.assertRaisesRegex(
            ExecutableProfileError,
            "TRAEFIK_CONSTRAINT_LABEL",
        ):
            write_deployment_env(
                self.root,
                "felix",
                {"TRAEFIK_CONSTRAINT_LABEL": "not safe"},
                force=True,
            )

    def test_executable_secret_names_require_explicit_exact_policy(self) -> None:
        """Reject renderer-inferred secret naming behavior.

        Returns:
            Nothing.
        """

        invalid = copy.deepcopy(self.felix_config)
        invalid["secretsConfig"]["prefixed"] = True
        self._write_config("felix", invalid)

        with self.assertRaisesRegex(
            ExecutableProfileError,
            "secretsConfig.prefixed=false",
        ):
            load_config_defaults(self.root, "felix")

    def test_keycloak_clients_use_exact_profile_callbacks_and_origins(self) -> None:
        """Build mobile/Web callback and audience clients from profile data.

        Returns:
            Nothing.
        """

        profile = self._configure("felix", self.felix_config)
        identity = load_keycloak_identity(profile)
        frontend = _frontend_payload(identity)
        backend = _backend_payload(identity)

        self.assertEqual(
            frontend["redirectUris"],
            [
                "https://felix-app.fe-wi.com/auth/callback",
                "felixkc:/callback",
            ],
        )
        self.assertEqual(
            frontend["webOrigins"],
            ["https://felix-app.fe-wi.com"],
        )
        self.assertIs(frontend["publicClient"], True)
        self.assertEqual(
            frontend["attributes"]["pkce.code.challenge.method"],
            "S256",
        )
        self.assertEqual(
            frontend["attributes"]["post.logout.redirect.uris"],
            (
                "https://felix-app.fe-wi.com/auth/callback"
                "##felixkc:/callback"
                "##https://felix-app.fe-wi.com/*"
            ),
        )
        self.assertIs(backend["publicClient"], False)
        self.assertIs(backend["serviceAccountsEnabled"], True)

    def test_keycloak_bootstrap_policy_is_normalized_from_profile(self) -> None:
        """Normalize realm, mapper, and forbidden-user policy as typed data.

        Returns:
            Nothing.
        """

        profile = self._configure("felix", self.felix_config)
        identity = load_keycloak_identity(profile)

        self.assertEqual(identity.realm_display_name, "Felix")
        self.assertEqual(
            dict(identity.realm_settings),
            self.felix_config["auth"]["realmSettings"],
        )
        self.assertEqual(
            identity.audience_mapper_name,
            "backend-audience",
        )
        self.assertEqual(
            identity.forbidden_default_usernames,
            ("test",),
        )

    def test_keycloak_bootstrap_policy_rejects_invalid_schema_values(
        self,
    ) -> None:
        """Reject unsupported realm, mapper, and forbidden-user policy data.

        Returns:
            Nothing.
        """

        invalid_settings = copy.deepcopy(self.felix_config)
        invalid_settings["auth"]["realmSettings"]["unsupported"] = True
        invalid_mapper = copy.deepcopy(self.felix_config)
        invalid_mapper["auth"]["audienceMapperName"] = "not safe"
        invalid_users = copy.deepcopy(self.felix_config)
        invalid_users["auth"]["forbiddenDefaultUsernames"] = [
            "test",
            "test",
        ]
        disabled_realm = copy.deepcopy(self.felix_config)
        disabled_realm["auth"]["realmSettings"]["enabled"] = False
        missing_roles = copy.deepcopy(self.felix_config)
        del missing_roles["auth"]["serviceAccountClientRoles"]
        shared_client = copy.deepcopy(self.felix_config)
        shared_client["auth"]["adminClientId"] = shared_client["auth"][
            "frontendClientId"
        ]
        reserved_client = copy.deepcopy(self.felix_config)
        reserved_client["auth"]["adminClientId"] = "realm-management"
        master_realm = copy.deepcopy(self.felix_config)
        master_realm["auth"]["realm"] = "master"
        master_realm["auth"]["issuerUrl"] = (
            "https://keycloak.fe-wi.com/realms/master"
        )
        master_realm["auth"]["jwksUrl"] = (
            "https://keycloak.fe-wi.com/realms/master/"
            "protocol/openid-connect/certs"
        )
        cases = (
            (invalid_settings, "realmSettings contains unsupported fields"),
            (invalid_mapper, "audienceMapperName is unsafe"),
            (invalid_users, "forbiddenDefaultUsernames must be unique"),
            (disabled_realm, "realmSettings.enabled must be true"),
            (missing_roles, "missing required keys: serviceAccountClientRoles"),
            (shared_client, "frontendClientId and auth.adminClientId must differ"),
            (reserved_client, "must not use built-in clients"),
            (master_realm, "must not target Keycloak's master realm"),
        )

        for invalid, message in cases:
            with self.subTest(expected=message):
                self._write_config("felix", invalid)
                with self.assertRaisesRegex(
                    ExecutableProfileError,
                    message,
                ):
                    load_config_defaults(self.root, "felix")

    def test_operator_deployment_defaults_can_be_overridden(self) -> None:
        """Allow validated stack, routing, image, and resource choices.

        Returns:
            Nothing.
        """

        profile = self._configure(
            "felix",
            self.felix_config,
            {
                "STACK_NAME": "felix-test",
                "API_BASE_URL": "https://api.test-felix.example.com",
                "DOMAIN": "api.test-felix.example.com",
                "WEB_BASE_URL": "https://test-felix.example.com",
                "WEB_DOMAIN": "test-felix.example.com",
                "CORS_ORIGINS": "https://test-felix.example.com",
                "IMAGE_NAME": "sokrates1989/python-api-felix-test",
                "WEB_IMAGE_NAME": "sokrates1989/flutter-felix-test-web",
                "API_REPLICAS": "2",
                "WEB_REPLICAS": "2",
            },
        )

        self.assertEqual(profile.stack_name, "felix-test")
        self.assertEqual(
            profile.image_reference,
            "sokrates1989/python-api-felix-test:0.1.1",
        )
        self.assertEqual(
            profile.web_image_reference,
            "sokrates1989/flutter-felix-test-web:1.0.5",
        )
        identity = load_keycloak_identity(profile)
        self.assertIn(
            "https://test-felix.example.com/auth/callback",
            identity.redirect_uris,
        )
        self.assertEqual(
            identity.web_origins,
            ("https://test-felix.example.com",),
        )

    def test_application_identity_cannot_be_overridden(self) -> None:
        """Reject attempts to override profile and authentication identity.

        Returns:
            Nothing.
        """

        self._write_config("felix", self.felix_config)
        with self.assertRaisesRegex(
            ExecutableProfileError,
            "cannot be overridden",
        ):
            write_deployment_env(
                self.root,
                "felix",
                {"KEYCLOAK_REALM": "other"},
                force=True,
            )

    def test_mutable_release_tags_are_rejected(self) -> None:
        """Reject latest as an executable profile release image.

        Returns:
            Nothing.
        """

        invalid = copy.deepcopy(self.felix_config)
        invalid["image"]["defaultVersion"] = "latest"
        self._write_config("felix", invalid)
        with self.assertRaisesRegex(
            ExecutableProfileError,
            "semantic version",
        ):
            load_config_defaults(self.root, "felix")

    def test_schema_version_is_written_from_profile(self) -> None:
        """Keep generated environment schema metadata aligned with JSON.

        Returns:
            Nothing.
        """

        self._configure("felix", self.felix_config)
        environment = (self.root / ".env").read_text(encoding="utf-8")

        self.assertIn("PROFILE_SCHEMA_VERSION=5.0\n", environment)
        self.assertNotIn("prod.env", environment)

    def test_tracked_template_uses_the_same_executable_path(self) -> None:
        """Validate the reusable new-app template through the shared loader.

        Returns:
            Nothing.
        """

        template = json.loads(
            (REPOSITORY_ROOT / "site-configs" / "_template.json").read_text(
                encoding="utf-8"
            )
        )
        profile = self._configure("example", template)
        stack = render_stack(profile)

        self.assertEqual(profile.app_id, "example_app")
        self.assertIn("your-username/flutter-example-app-web:0.1.0", stack)
        self.assertIn("example-app-frontend", json.dumps(profile.data))


if __name__ == "__main__":
    unittest.main()
