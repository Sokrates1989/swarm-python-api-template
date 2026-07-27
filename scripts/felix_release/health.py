"""Strict replicas, HTTPS, runtime identity, auth, and migration health.

The health gate validates the digest-bound Swarm services and the public Felix
API, rejects anonymous protected-route access, checks candidate discovery and
JWKS, and conservatively scans recent logs for likely credential disclosure.
"""

from __future__ import annotations

import hashlib
import json
import re
import ssl
from typing import Any
from urllib import error, request

from .command import CommandRunner
from .errors import FelixReleaseError
from .models import HealthEvidence, ImageIdentity
from .preflight import CANDIDATE_API_ORIGIN, CANDIDATE_ISSUER


SERVICE_NAMES = (
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


def _scan_service_logs(runner: CommandRunner) -> int:
    """Scan recent API logs and refuse likely credential leakage.

    Args:
        runner: Shell-free command runner.

    Returns:
        Number of scanned log lines.

    Raises:
        FelixReleaseError: If a sensitive value pattern appears.
    """

    logs = runner.run(
        [
            "docker",
            "service",
            "logs",
            "--raw",
            "--tail",
            "500",
            "felix-new_api",
        ],
        check=False,
    )
    combined = f"{logs.stdout}\n{logs.stderr}"
    if SENSITIVE_LOG_PATTERN.search(combined):
        raise FelixReleaseError("Recent API logs contain a sensitive-value pattern.")
    return len(combined.splitlines())


def run_strict_health(
    runner: CommandRunner,
    image: ImageIdentity,
) -> HealthEvidence:
    """Run every required post-deployment health assertion.

    Args:
        runner: Shell-free command runner.
        image: Expected immutable candidate API image.

    Returns:
        Sanitized strict health evidence.

    Raises:
        FelixReleaseError: If any replica, image, TLS, API, migration, protected
            route, discovery/JWKS, version, or log check fails.
    """

    service_images: dict[str, str] = {}
    checks: dict[str, bool] = {}
    for service_name in SERVICE_NAMES:
        service_image, replicas_healthy = _service_evidence(runner, service_name)
        service_images[service_name] = service_image
        checks[f"replicas:{service_name}"] = replicas_healthy
    checks["apiImageDigest"] = (
        service_images["felix-new_api"] == image.digest_reference
    )
    api_health = _https_json(f"{CANDIDATE_API_ORIGIN}/health", "Felix API health")
    checks.update(_validate_api_health(api_health))
    version = _https_json(f"{CANDIDATE_API_ORIGIN}/version", "Felix API version")
    checks["apiVersion"] = version.get("IMAGE_TAG") == image.version
    protected_status, _ = _https_response(f"{CANDIDATE_API_ORIGIN}/v1/dashboard")
    checks["protectedRouteRejectsAnonymous"] = protected_status in {401, 403}
    checks.update(_keycloak_health_checks())
    log_lines = _scan_service_logs(runner)
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
    fingerprint = hashlib.sha256(
        json.dumps(safe_health, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    evidence = HealthEvidence(checks, service_images, fingerprint, log_lines)
    if not evidence.healthy:
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise FelixReleaseError("Strict Felix health failed: " + ", ".join(failed))
    return evidence
