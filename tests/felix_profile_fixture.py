"""
Module: felix_profile_fixture.py

Description:
    Provides the canonical public Felix full-stack deployment mapping shared by
    strict profile, renderer, and release-state-machine tests.
"""

from __future__ import annotations

from collections.abc import Mapping


PRODUCTION_PROFILE: Mapping[str, str] = {
    "PROFILE_SCHEMA_VERSION": "2",
    "DEPLOYMENT_PROFILE_ID": "felix",
    "APP_ID": "felix",
    "APP_ENVIRONMENT": "production",
    "APP_PROFILE": "felix",
    "BACKEND_APP_ID": "felix",
    "BACKEND_DATA_PROFILE": "postgresql",
    "AUTH_PROVIDER": "keycloak",
    "API_BASE_URL": "https://api.felix-app.fe-wi.com",
    "DOMAIN": "api.felix-app.fe-wi.com",
    "WEB_BASE_URL": "https://felix-app.fe-wi.com",
    "WEB_DOMAIN": "felix-app.fe-wi.com",
    "CORS_ORIGINS": "https://felix-app.fe-wi.com",
    "KEYCLOAK_BASE_URL": "https://keycloak.fe-wi.com",
    "KEYCLOAK_ISSUER_URL": "https://keycloak.fe-wi.com/realms/felix-new",
    "KEYCLOAK_REALM": "felix-new",
    "KEYCLOAK_AUDIENCE": "felix-new-backend",
    "KEYCLOAK_FRONTEND_CLIENT_ID": "felix-new-frontend",
    "STACK_NAME": "felix-new",
    "STACK_FAMILY": "api",
    "STACK_ROLE": "full-stack",
    "PRIMARY_SERVICE": "api",
    "DB_TYPE": "postgresql",
    "DB_MODE": "local",
    "DB_HOST": "postgres",
    "DB_PORT": "5432",
    "DB_NAME": "felix",
    "DB_USER": "felix",
    "PROXY_TYPE": "traefik",
    "SSL_MODE": "proxy",
    "TRAEFIK_NETWORK": "traefik-public",
    "API_PUBLISHED_PORT": "8083",
    "WEB_PUBLISHED_PORT": "8084",
    "IMAGE_NAME": "sokrates1989/python-api-felix",
    "IMAGE_VERSION": "0.1.1",
    "API_REPLICAS": "1",
    "MEMORY_LIMIT": "512M",
    "DATA_ROOT": "/swarm/volumes/felix-new",
    "PGADMIN_ENABLED": "false",
    "PGADMIN_DOMAIN": "disabled",
    "PGADMIN_EMAIL": "disabled",
    "PGADMIN_REPLICAS": "0",
    "WEB_ENABLED": "true",
    "WEB_IMAGE_NAME": "sokrates1989/flutter-felix-web",
    "WEB_IMAGE_VERSION": "1.0.5",
    "WEB_REPLICAS": "1",
    "WEB_MEMORY_LIMIT": "128M",
}


def production_profile(**overrides: str) -> dict[str, str]:
    """Create one mutable canonical profile with optional field overrides.

    Args:
        **overrides: Public field replacements applied after copying the
            canonical mapping.

    Returns:
        Independent mutable deployment-profile mapping.
    """

    values = dict(PRODUCTION_PROFILE)
    values.update(overrides)
    return values
