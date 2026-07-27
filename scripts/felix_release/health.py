"""Strict replicas, HTTPS, runtime identity, auth, and migration health.

The health gate validates the digest-bound Swarm services and the public Felix
WebApp/API, rejects anonymous protected-route access, checks candidate
discovery/JWKS, and scans recent public-service logs for credential patterns.
"""

from __future__ import annotations

import hashlib
import json
import re
import ssl
from collections.abc import Sequence
from typing import Any
from urllib import error, request

from .command import CommandRunner
from .errors import FelixReleaseError
from .models import HealthEvidence, ImageIdentity
from felix_site_contract import FelixSiteProfile

from .preflight import (
    CANDIDATE_API_ORIGIN,
    CANDIDATE_ISSUER,
    CANDIDATE_WEB_ORIGIN,
)


SERVICE_NAMES = (
    "felix-new_web",
    "felix-new_api",
    "felix-new_postgres",
    "felix-new_redis",
)
SENSITIVE_LOG_PATTERN = re.compile(
    r"(?i)(authorization\s*[:=]|bearer\s+[a-z0-9._~-]+|"
    r"(password|client_secret|api_key|private_key)\s*[:=]\s*\S+)"
)


def _json_object(text: str, context: str) -> dict[str, Any]:
    """Parse one required JSON object.

    Args:
        text: JSON text.
        context: Safe diagnostic label.

    Returns:
        Parsed object mapping.

    Raises:
        FelixReleaseError: If parsing or type validation fails.
    """

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FelixReleaseError(f"Invalid JSON from {context}.") from exc
    if not isinstance(value, dict):
        raise FelixReleaseError(f"Expected an object from {context}.")
    return value


def _https_response(url: str) -> tuple[int, bytes]:
    """Fetch one HTTPS endpoint with normal certificate verification.

    Args:
        url: Exact public HTTPS endpoint.

    Returns:
        HTTP status and response bytes. HTTP error statuses are returned rather
        than raised so protected-route behavior can be asserted.

    Raises:
        FelixReleaseError: If DNS, TLS, timeout, or transport fails.
    """

    outbound = request.Request(url, headers={"Accept": "application/json"})
    try:
        with request.urlopen(
            outbound,
            timeout=15,
            context=ssl.create_default_context(),
        ) as response:
            return response.status, response.read()
    except error.HTTPError as exc:
        return exc.code, exc.read()
    except (error.URLError, TimeoutError, OSError) as exc:
        raise FelixReleaseError(f"Verified HTTPS request failed for {url}.") from exc


def _https_json(url: str, context: str) -> dict[str, Any]:
    """Fetch and parse one successful verified HTTPS JSON object.

    Args:
        url: Exact public HTTPS endpoint.
        context: Safe diagnostic label.

    Returns:
        Parsed JSON object.

    Raises:
        FelixReleaseError: If status is not 200 or JSON is invalid.
    """

    status, body = _https_response(url)
    if status != 200:
        raise FelixReleaseError(f"{context} returned HTTP {status}.")
    return _json_object(body.decode("utf-8"), context)


def _service_evidence(
    runner: CommandRunner,
    service_name: str,
) -> tuple[str, bool]:
    """Inspect one service image and replica convergence.

    Args:
        runner: Shell-free command runner.
        service_name: Exact candidate stack service name.

    Returns:
        Service image reference and replica-health boolean.

    Raises:
        FelixReleaseError: If service inspect is malformed.
    """

    inspected = runner.run(
        ["docker", "service", "inspect", service_name, "--format", "{{json .}}"]
    )
    service = _json_object(inspected.stdout, f"service {service_name}")
    spec = service.get("Spec", {})
    mode = spec.get("Mode", {}).get("Replicated", {})
    status = service.get("ServiceStatus", {})
    desired = int(mode.get("Replicas", 0))
    running = int(status.get("RunningTasks", -1))
    desired_tasks = int(status.get("DesiredTasks", -2))
    image = str(
        spec.get("TaskTemplate", {}).get("ContainerSpec", {}).get("Image", "")
    )
    healthy = desired > 0 and running == desired == desired_tasks
    if not image:
        raise FelixReleaseError(f"Service {service_name} has no image.")
    return image, healthy


def _validate_api_health(payload: dict[str, Any]) -> dict[str, bool]:
    """Validate exact Felix production runtime and migration identity.

    Args:
        payload: API ``/health`` JSON object.

    Returns:
        Named boolean checks.
    """

    keycloak = payload.get("keycloak", {})
    return {
        "apiStatus": payload.get("status") == "OK",
        "productionEnvironment": payload.get("app_environment") == "production",
        "appProfile": payload.get("app_profile") == "felix",
        "runtimeApp": payload.get("backend_app_id") == "felix",
        "buildApp": payload.get("build_backend_app_id") == "felix",
        "dataProfile": payload.get("backend_data_profile") == "postgresql",
        "provider": payload.get("provider_profile") == "sql",
        "startupProbe": payload.get("startup_probe_status") == "success",
        "startupComplete": payload.get("startup_complete") is True,
        "migration": payload.get("migration_status") == "success",
        "authProvider": payload.get("auth_provider") == "keycloak",
        "keycloakConfigured": keycloak.get("configured") is True,
        "keycloakRealm": keycloak.get("realm") == "felix-new",
        "keycloakIssuer": keycloak.get("issuer") == CANDIDATE_ISSUER,
        "keycloakAudience": keycloak.get("audience") == "felix-new-backend",
        "audienceEnforced": keycloak.get("audience_enforced") is True,
    }


def _validate_web_metadata(
    payload: dict[str, Any],
    image: ImageIdentity,
) -> dict[str, bool]:
    """Validate public WebApp release metadata against its exact image.

    Args:
        payload: WebApp `/release-metadata.json` object.
        image: Resolved immutable WebApp image identity.

    Returns:
        Named public identity checks.
    """

    return {
        "webMetadataKind": payload.get("kind") == "flutter-web-release",
        "webAppId": payload.get("appId") == "felix",
        "webAppPath": payload.get("appPath") == "apps/felix",
        "webEnvironment": payload.get("environment") == "production",
        "webImageRepository": (
            payload.get("imageRepository") == image.tag_reference.rsplit(":", 1)[0]
        ),
        "webVersion": payload.get("imageTag") == image.version,
        "webProfileFingerprint": (
            payload.get("profileFingerprint") == image.profile_fingerprint
        ),
        "webSourceRevision": payload.get("sourceRevision") == image.revision,
        "webOrigin": payload.get("webOrigin") == CANDIDATE_WEB_ORIGIN,
        "webBackendOrigin": payload.get("backendOrigin") == CANDIDATE_API_ORIGIN,
        "webKeycloakIssuer": payload.get("keycloakIssuer") == CANDIDATE_ISSUER,
        "webKeycloakRealm": payload.get("keycloakRealm") == "felix-new",
        "webKeycloakClient": (
            payload.get("keycloakClientId") == "felix-new-frontend"
        ),
        "webCleanSource": payload.get("sourceDirty") is False,
    }


def _keycloak_health_checks() -> dict[str, bool]:
    """Verify exact candidate discovery issuer and non-empty JWKS.

    Returns:
        Named discovery/JWKS checks.

    Raises:
        FelixReleaseError: If verified HTTPS/JSON requests fail.
    """

    discovery = _https_json(
        f"{CANDIDATE_ISSUER}/.well-known/openid-configuration",
        "candidate OIDC discovery",
    )
    jwks = _https_json(
        f"{CANDIDATE_ISSUER}/protocol/openid-connect/certs",
        "candidate JWKS",
    )
    return {
        "oidcIssuer": discovery.get("issuer") == CANDIDATE_ISSUER,
        "jwksKeys": bool(jwks.get("keys")),
    }


def _scan_service_logs(
    runner: CommandRunner,
    service_names: Sequence[str],
) -> int:
    """Scan recent public-service logs and refuse credential patterns.

    Args:
        runner: Shell-free command runner.
        service_names: Exact candidate public service names.

    Returns:
        Number of scanned log lines.

    Raises:
        FelixReleaseError: If a sensitive value pattern appears.
    """

    scanned_lines = 0
    for service_name in service_names:
        logs = runner.run(
            [
                "docker",
                "service",
                "logs",
                "--raw",
                "--tail",
                "500",
                service_name,
            ],
            check=False,
        )
        combined = f"{logs.stdout}\n{logs.stderr}"
        if SENSITIVE_LOG_PATTERN.search(combined):
            raise FelixReleaseError(
                f"Recent {service_name} logs contain a sensitive-value pattern."
            )
        scanned_lines += len(combined.splitlines())
    return scanned_lines


def _collect_service_health(
    runner: CommandRunner,
    image: ImageIdentity,
    web_image: ImageIdentity,
    profile: FelixSiteProfile,
) -> tuple[dict[str, str], dict[str, bool]]:
    """Collect replica and immutable-image checks for active services.

    Args:
        runner: Shell-free command runner.
        image: Expected immutable API image.
        web_image: Expected immutable WebApp image.
        profile: Validated profile controlling optional pgAdmin.

    Returns:
        Service-image mapping and named service checks.
    """

    service_names = list(SERVICE_NAMES)
    if profile.deployment["PGADMIN_ENABLED"] == "true":
        service_names.append("felix-new_pgadmin")
    service_images: dict[str, str] = {}
    checks: dict[str, bool] = {}
    for service_name in service_names:
        service_image, replicas_healthy = _service_evidence(runner, service_name)
        service_images[service_name] = service_image
        checks[f"replicas:{service_name}"] = replicas_healthy
    checks["apiImageDigest"] = (
        service_images["felix-new_api"] == image.digest_reference
    )
    checks["webImageDigest"] = (
        service_images["felix-new_web"] == web_image.digest_reference
    )
    return service_images, checks


def _collect_public_health(
    image: ImageIdentity,
    web_image: ImageIdentity,
) -> tuple[dict[str, bool], dict[str, Any], dict[str, Any]]:
    """Collect WebApp/API HTTPS, identity, auth, and migration checks.

    Args:
        image: Expected immutable API image.
        web_image: Expected immutable WebApp image.

    Returns:
        Named checks, sanitized API health, and public WebApp metadata.

    Raises:
        FelixReleaseError: If HTTPS or JSON endpoints cannot be verified.
    """

    checks: dict[str, bool] = {}
    web_status, _ = _https_response(f"{CANDIDATE_WEB_ORIGIN}/health")
    checks["webHttpsHealth"] = web_status == 200
    web_metadata = _https_json(
        f"{CANDIDATE_WEB_ORIGIN}/release-metadata.json",
        "Felix WebApp metadata",
    )
    checks.update(_validate_web_metadata(web_metadata, web_image))
    api_health = _https_json(f"{CANDIDATE_API_ORIGIN}/health", "Felix API health")
    checks.update(_validate_api_health(api_health))
    version = _https_json(f"{CANDIDATE_API_ORIGIN}/version", "Felix API version")
    checks["apiVersion"] = version.get("IMAGE_TAG") == image.version
    protected_status, _ = _https_response(f"{CANDIDATE_API_ORIGIN}/v1/dashboard")
    checks["protectedRouteRejectsAnonymous"] = protected_status in {401, 403}
    checks.update(_keycloak_health_checks())
    return checks, api_health, web_metadata


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    """Hash one sanitized public health/metadata object.

    Args:
        payload: Secret-free public evidence mapping.

    Returns:
        Lowercase canonical SHA-256.
    """

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def run_strict_health(
    runner: CommandRunner,
    image: ImageIdentity,
    web_image: ImageIdentity,
    profile: FelixSiteProfile,
) -> HealthEvidence:
    """Run every required post-deployment health assertion.

    Args:
        runner: Shell-free command runner.
        image: Expected immutable candidate API image.
        web_image: Expected immutable candidate WebApp image.
        profile: Validated profile controlling optional services.

    Returns:
        Sanitized strict health evidence.

    Raises:
        FelixReleaseError: If any replica, image, TLS, API, migration, protected
            route, discovery/JWKS, version, or log check fails.
    """

    service_images, checks = _collect_service_health(
        runner,
        image,
        web_image,
        profile,
    )
    public_checks, api_health, web_metadata = _collect_public_health(
        image,
        web_image,
    )
    checks.update(public_checks)
    log_lines = _scan_service_logs(
        runner,
        ("felix-new_web", "felix-new_api"),
    )
    checks["recentLogsSecretSafe"] = True
    safe_health = {
        key: api_health.get(key)
        for key in (
            "status",
            "app_environment",
            "app_profile",
            "backend_app_id",
            "backend_data_profile",
            "provider_profile",
            "startup_probe_status",
            "startup_complete",
            "migration_status",
            "auth_provider",
        )
    }
    evidence = HealthEvidence(
        checks,
        service_images,
        _payload_fingerprint(safe_health),
        log_lines,
        _payload_fingerprint(web_metadata),
    )
    if not evidence.healthy:
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise FelixReleaseError("Strict Felix health failed: " + ", ".join(failed))
    return evidence
