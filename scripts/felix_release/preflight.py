"""Strict profile, Docker, registry, storage, DNS/TLS, and identity preflight.

The preflight resolves semantic Felix WebApp and API tags to immutable registry
digests, validates their OCI identities/platforms, renders a secret-free
digest-bound stack, and requires exact Swarm plus public identity state.
"""

from __future__ import annotations

import json
import re
import socket
import ssl
from pathlib import Path
from typing import Any
from urllib import error, request

from felix_site_contract import FelixSiteProfile, load_felix_site_profile
from felix_stack_renderer import render_stack, validate_rendered_stack
from felix_web_stack import web_image_reference

from .command import CommandRunner
from .errors import FelixReleaseError
from .images import resolve_image_identity, resolve_web_image_identity
from .models import ImageIdentity, PreflightEvidence


CANDIDATE_STACK = "felix-new"
CANDIDATE_WEB_HOST = "felix-app.fe-wi.com"
CANDIDATE_WEB_ORIGIN = f"https://{CANDIDATE_WEB_HOST}"
CANDIDATE_API_HOST = "api.felix-app.fe-wi.com"
CANDIDATE_API_ORIGIN = f"https://{CANDIDATE_API_HOST}"
CANDIDATE_ISSUER = "https://keycloak.fe-wi.com/realms/felix-new"
LEGACY_WEB_ORIGIN = "https://felix.app.fe-wi.com"
LEGACY_DISCOVERY = (
    "https://keycloak.fe-wi.com/realms/felixappnew/"
    ".well-known/openid-configuration"
)
SECRET_TEXT_PATTERN = re.compile(
    r"(?i)(password|client_secret|api_key|private_key)\s*[:=]\s*[^\s]+"
)


def required_data_directories(profile: FelixSiteProfile) -> tuple[Path, ...]:
    """Resolve exact candidate host data directories.

    Args:
        profile: Validated Felix site profile.

    Returns:
        Active PostgreSQL/pgAdmin plus backup and API-log directories below
        the selected data root.
    """

    root = Path(profile.deployment["DATA_ROOT"])
    directories = [root / "backups", root / "logs" / "api"]
    if profile.deployment["DB_MODE"] == "local":
        directories.insert(0, root / "postgres_data")
    if profile.deployment["PGADMIN_ENABLED"] == "true":
        directories.append(root / "pgadmin")
    return tuple(directories)


def prepare_data_directories(root: Path) -> tuple[str, ...]:
    """Create only the exact candidate storage directories.

    Args:
        root: Swarm repository root containing validated root ``.env``.

    Returns:
        Absolute created/verified directory paths.

    Raises:
        FelixReleaseError: If profile validation or directory creation fails.

    Side Effects:
        Creates the candidate PostgreSQL, backup, and API-log directories.
    """

    try:
        profile = load_felix_site_profile(root)
    except Exception as exc:
        raise FelixReleaseError("Felix .env/site profile validation failed.") from exc
    try:
        directories = required_data_directories(profile)
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)
            if directory.name == "pgadmin":
                directory.chown(5050, 5050)
    except OSError as exc:
        raise FelixReleaseError("Unable to create candidate data directories.") from exc
    return tuple(str(directory) for directory in directories)


def _load_json(text: str, context: str) -> Any:
    """Parse JSON returned by a trusted local or HTTPS endpoint.

    Args:
        text: JSON text.
        context: Safe failure label.

    Returns:
        Parsed JSON value.

    Raises:
        FelixReleaseError: If JSON is malformed.
    """

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise FelixReleaseError(f"Invalid JSON from {context}.") from exc


def _digest_bound_stack(
    profile: FelixSiteProfile,
    image: ImageIdentity,
    web_image: ImageIdentity,
) -> str:
    """Replace exact semantic API/WebApp tags with immutable digests.

    Args:
        profile: Validated Felix candidate profile.
        image: Resolved immutable API image identity.
        web_image: Resolved immutable WebApp image identity.

    Returns:
        Secret-free digest-bound Swarm Compose text.

    Raises:
        FelixReleaseError: If either semantic image occurs other than once.
    """

    rendered = render_stack(profile)
    validate_rendered_stack(rendered, profile)
    replacements = (
        (profile.image_reference, image.digest_reference, "API"),
        (web_image_reference(profile), web_image.digest_reference, "WebApp"),
    )
    digest_stack = rendered
    for semantic, digest, component in replacements:
        source = f'    image: "{semantic}"'
        target = f'    image: "{digest}"'
        if digest_stack.count(source) != 1:
            raise FelixReleaseError(
                f"Rendered stack {component} image replacement is ambiguous."
            )
        digest_stack = digest_stack.replace(source, target, 1)
    if SECRET_TEXT_PATTERN.search(digest_stack) or "${" in digest_stack:
        raise FelixReleaseError("Digest-bound stack contains unsafe material.")
    return digest_stack


def write_digest_bound_stack(
    root: Path,
    profile: FelixSiteProfile,
    image: ImageIdentity,
    web_image: ImageIdentity,
    runner: CommandRunner,
) -> Path:
    """Write and validate the exact runtime-only digest-bound stack.

    Args:
        root: Swarm repository root.
        profile: Validated Felix candidate profile.
        image: Resolved immutable API image identity.
        web_image: Resolved immutable WebApp image identity.
        runner: Shell-free command runner.

    Returns:
        Generated ignored Compose path.

    Raises:
        FelixReleaseError: If writing or Docker stack config validation fails.

    Side Effects:
        Writes ``build/felix-release/deploy-stack.yml``.
    """

    output = root / "build" / "felix-release" / "deploy-stack.yml"
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            _digest_bound_stack(profile, image, web_image),
            encoding="utf-8",
        )
    except OSError as exc:
        raise FelixReleaseError("Unable to write digest-bound deploy stack.") from exc
    configured = runner.run(
        ["docker", "stack", "config", "--compose-file", str(output)]
    ).stdout
    if "${" in configured or SECRET_TEXT_PATTERN.search(configured):
        raise FelixReleaseError("Docker stack config exposed unsafe material.")
    return output


def _verify_swarm(runner: CommandRunner) -> None:
    """Require an active amd64 Linux Swarm manager.

    Args:
        runner: Shell-free command runner.

    Returns:
        None.

    Raises:
        FelixReleaseError: If Docker is not an active compatible manager.
    """

    info = _load_json(
        runner.run(["docker", "info", "--format", "{{json .}}"]).stdout,
        "Docker info",
    )
    swarm = info.get("Swarm", {}) if isinstance(info, dict) else {}
    if (
        swarm.get("LocalNodeState") != "active"
        or not swarm.get("ControlAvailable")
        or info.get("OSType") != "linux"
        or info.get("Architecture") != "x86_64"
    ):
        raise FelixReleaseError("Docker host is not an active amd64 Swarm manager.")


def _verify_docker_resources(
    runner: CommandRunner,
    profile: FelixSiteProfile,
) -> tuple[str, ...]:
    """Require every external secret and the exact overlay network.

    Args:
        runner: Shell-free command runner.
        profile: Validated Felix candidate profile.

    Returns:
        Verified Docker secret names.

    Raises:
        FelixReleaseError: If a secret/network is absent or incompatible.
    """

    secret_names = [mount.name for mount in profile.secret_mounts]
    if profile.deployment["PGADMIN_ENABLED"] == "true":
        database = profile.data["database"]
        if not isinstance(database, dict):
            raise FelixReleaseError("Felix database profile is not an object.")
        secret_names.append(str(database["pgadminSecret"]))
    for name in secret_names:
        runner.run(["docker", "secret", "inspect", name])
    if profile.deployment["PROXY_TYPE"] != "traefik":
        return tuple(secret_names)
    network_name = profile.deployment["TRAEFIK_NETWORK"]
    network = _load_json(
        runner.run(["docker", "network", "inspect", network_name]).stdout,
        "Docker network inspect",
    )
    if (
        not isinstance(network, list)
        or len(network) != 1
        or network[0].get("Scope") != "swarm"
        or network[0].get("Driver") != "overlay"
    ):
        raise FelixReleaseError("Candidate Traefik network is not a Swarm overlay.")
    return tuple(secret_names)


def _verify_data_directories(profile: FelixSiteProfile) -> tuple[str, ...]:
    """Require exact pre-created candidate data directories.

    Args:
        profile: Validated Felix candidate profile.

    Returns:
        Verified absolute directory paths.

    Raises:
        FelixReleaseError: If a directory is absent or resolves elsewhere.
    """

    directories = required_data_directories(profile)
    for directory in directories:
        if not directory.is_dir():
            raise FelixReleaseError(f"Candidate data directory is missing: {directory}.")
    return tuple(str(directory.resolve()) for directory in directories)


def _verified_json_url(url: str, context: str) -> dict[str, Any]:
    """Fetch one JSON document over verified TLS.

    Args:
        url: Public HTTPS URL.
        context: Safe failure label.

    Returns:
        Parsed JSON object.

    Raises:
        FelixReleaseError: If TLS, HTTP, or JSON validation fails.
    """

    try:
        with request.urlopen(url, timeout=15, context=ssl.create_default_context()) as response:
            body = response.read()
    except (error.URLError, TimeoutError, OSError) as exc:
        raise FelixReleaseError(f"Verified HTTPS request failed for {context}.") from exc
    parsed = _load_json(body.decode("utf-8"), context)
    if not isinstance(parsed, dict):
        raise FelixReleaseError(f"Expected an object from {context}.")
    return parsed


def _verify_dns_and_tls(hostname: str) -> None:
    """Require public DNS and a trusted certificate for one hostname.

    Args:
        hostname: Exact candidate or legacy public hostname.

    Returns:
        None.

    Raises:
        FelixReleaseError: If DNS or the certificate handshake fails.
    """

    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        if not addresses:
            raise FelixReleaseError(f"DNS returned no address for {hostname}.")
        with socket.create_connection((hostname, 443), timeout=10) as raw_socket:
            with ssl.create_default_context().wrap_socket(
                raw_socket,
                server_hostname=hostname,
            ):
                pass
    except (OSError, ssl.SSLError) as exc:
        raise FelixReleaseError(f"DNS/TLS verification failed for {hostname}.") from exc


def verify_public_identity_continuity() -> None:
    """Verify candidate discovery/JWKS and protected legacy reachability.

    Returns:
        None.

    Raises:
        FelixReleaseError: If candidate identity or legacy public evidence fails.
    """

    discovery_url = f"{CANDIDATE_ISSUER}/.well-known/openid-configuration"
    discovery = _verified_json_url(discovery_url, "candidate OIDC discovery")
    if discovery.get("issuer") != CANDIDATE_ISSUER:
        raise FelixReleaseError("Candidate Keycloak issuer does not match.")
    jwks = _verified_json_url(
        f"{CANDIDATE_ISSUER}/protocol/openid-connect/certs",
        "candidate JWKS",
    )
    if not jwks.get("keys"):
        raise FelixReleaseError("Candidate Keycloak JWKS contains no keys.")
    legacy = _verified_json_url(LEGACY_DISCOVERY, "legacy OIDC discovery")
    if legacy.get("issuer") != "https://keycloak.fe-wi.com/realms/felixappnew":
        raise FelixReleaseError("Legacy OIDC discovery identity changed.")
    try:
        with request.urlopen(
            LEGACY_WEB_ORIGIN,
            timeout=15,
            context=ssl.create_default_context(),
        ) as response:
            if response.status >= 400:
                raise FelixReleaseError("Legacy web application is unavailable.")
    except (error.URLError, TimeoutError, OSError) as exc:
        raise FelixReleaseError("Legacy web availability check failed.") from exc


def run_preflight(root: Path, runner: CommandRunner) -> PreflightEvidence:
    """Execute every strict pre-deployment gate and render the deploy stack.

    Args:
        root: Swarm repository root.
        runner: Shell-free command runner.

    Returns:
        Sanitized preflight evidence.

    Raises:
        FelixReleaseError: If profile, image, Docker, storage, TLS, Keycloak,
            legacy availability, or Compose validation fails.
    """

    try:
        profile = load_felix_site_profile(root)
    except Exception as exc:
        raise FelixReleaseError("Felix .env/site profile validation failed.") from exc
    if profile.deployment["DB_MODE"] != "local":
        raise FelixReleaseError(
            "Strict release currently requires local PostgreSQL backup ownership."
        )
    _verify_swarm(runner)
    secrets = _verify_docker_resources(runner, profile)
    directories = _verify_data_directories(profile)
    image = resolve_image_identity(runner, profile)
    web_image = resolve_web_image_identity(runner, profile)
    stack_path = write_digest_bound_stack(root, profile, image, web_image, runner)
    _verify_dns_and_tls(CANDIDATE_WEB_HOST)
    _verify_dns_and_tls(CANDIDATE_API_HOST)
    _verify_dns_and_tls("felix.app.fe-wi.com")
    verify_public_identity_continuity()
    return PreflightEvidence(
        profile.fingerprint,
        image,
        stack_path,
        secrets,
        directories,
        {
            "profileAndIdentity": True,
            "publishedImageDigestsAndPlatforms": True,
            "swarmManager": True,
            "dockerSecrets": True,
            "overlayNetwork": True,
            "dataDirectories": True,
            "composeConfig": True,
            "candidateDnsTls": True,
            "keycloakDiscoveryJwks": True,
            "legacyWebAndOidcUnchanged": True,
        },
        web_image,
    )
