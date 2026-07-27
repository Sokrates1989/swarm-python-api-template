"""Strict profile, Docker, registry, storage, DNS/TLS, and identity preflight.

The preflight resolves a semantic Felix tag to one immutable registry digest,
validates its OCI identity/platform, renders a secret-free digest-bound stack,
and requires the exact Swarm resources plus candidate and legacy public state.
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

from .command import CommandRunner
from .errors import FelixReleaseError
from .models import ImageIdentity, PreflightEvidence


CANDIDATE_STACK = "felix-new"
CANDIDATE_API_HOST = "api.felix-app.fe-wi.com"
CANDIDATE_API_ORIGIN = f"https://{CANDIDATE_API_HOST}"
CANDIDATE_ISSUER = "https://keycloak.fe-wi.com/realms/felix-new"
LEGACY_WEB_ORIGIN = "https://felix.app.fe-wi.com"
LEGACY_DISCOVERY = (
    "https://keycloak.fe-wi.com/realms/felixappnew/"
    ".well-known/openid-configuration"
)
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SECRET_TEXT_PATTERN = re.compile(
    r"(?i)(password|client_secret|api_key|private_key)\s*[:=]\s*[^\s]+"
)


def required_data_directories(profile: FelixSiteProfile) -> tuple[Path, ...]:
    """Resolve exact candidate host data directories.

    Args:
        profile: Validated Felix site profile.

    Returns:
        PostgreSQL, backup, and API-log directories below the fixed data root.
    """

    storage = profile.data["storage"]
    if not isinstance(storage, dict):
        raise FelixReleaseError("Felix storage profile is not an object.")
    root = Path(str(storage["dataRoot"]))
    return root / "postgres", root / "backups", root / "logs" / "api"


def prepare_data_directories(root: Path) -> tuple[str, ...]:
    """Create only the exact candidate storage directories.

    Args:
        root: Swarm repository root containing validated ``prod.env``.

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
        raise FelixReleaseError("Felix prod.env/site profile validation failed.") from exc
    try:
        directories = required_data_directories(profile)
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)
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


def resolve_image_identity(
    runner: CommandRunner,
    profile: FelixSiteProfile,
) -> ImageIdentity:
    """Pull and resolve the semantic image tag to an immutable digest.

    Args:
        runner: Shell-free command runner.
        profile: Validated Felix candidate profile.

    Returns:
        Verified OCI label, digest, and platform identity.

    Raises:
        FelixReleaseError: If pull, digest, labels, or platform are invalid.

    Side Effects:
        Pulls the selected semantic-version image into the local Docker cache.
    """

    tag_reference = profile.image_reference
    runner.run(["docker", "pull", tag_reference])
    inspected = _load_json(
        runner.run(["docker", "image", "inspect", tag_reference]).stdout,
        "Docker image inspect",
    )
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise FelixReleaseError("Docker image inspect did not return one image.")
    image = inspected[0]
    labels = image.get("Config", {}).get("Labels", {})
    repository = tag_reference.rsplit(":", 1)[0]
    repo_digests = [
        str(value)
        for value in image.get("RepoDigests", [])
        if str(value).startswith(f"{repository}@sha256:")
    ]
    if len(repo_digests) != 1:
        raise FelixReleaseError("Published Felix image has no unique registry digest.")
    digest_reference = repo_digests[0]
    digest = digest_reference.split("@", 1)[1]
    version = tag_reference.rsplit(":", 1)[1]
    revision = str(labels.get("org.opencontainers.image.revision", ""))
    lock_hash = str(labels.get("com.fe-wi.dependency-lock-sha256", ""))
    if (
        not DIGEST_PATTERN.fullmatch(digest)
        or labels.get("org.opencontainers.image.version") != version
        or labels.get("com.fe-wi.app-profile") != "felix"
        or labels.get("com.fe-wi.backend-app-id") != "felix"
        or not REVISION_PATTERN.fullmatch(revision)
        or not HASH_PATTERN.fullmatch(lock_hash)
    ):
        raise FelixReleaseError("Published Felix image labels/digest are invalid.")
    architecture = str(image.get("Architecture", ""))
    operating_system = str(image.get("Os", ""))
    if architecture != "amd64" or operating_system != "linux":
        raise FelixReleaseError("Felix image platform must be linux/amd64.")
    return ImageIdentity(
        tag_reference,
        digest_reference,
        digest,
        version,
        revision,
        lock_hash,
        architecture,
        operating_system,
    )


def _digest_bound_stack(profile: FelixSiteProfile, image: ImageIdentity) -> str:
    """Replace exactly one validated semantic API tag with its digest.

    Args:
        profile: Validated Felix candidate profile.
        image: Resolved immutable image identity.

    Returns:
        Secret-free digest-bound Swarm Compose text.

    Raises:
        FelixReleaseError: If the semantic image occurs other than once.
    """

    rendered = render_stack(profile)
    validate_rendered_stack(rendered, profile)
    source = f'    image: "{profile.image_reference}"'
    target = f'    image: "{image.digest_reference}"'
    if rendered.count(source) != 1:
        raise FelixReleaseError("Rendered stack API image replacement is ambiguous.")
    digest_stack = rendered.replace(source, target, 1)
    if SECRET_TEXT_PATTERN.search(digest_stack) or "${" in digest_stack:
        raise FelixReleaseError("Digest-bound stack contains unsafe material.")
    return digest_stack


def write_digest_bound_stack(
    root: Path,
    profile: FelixSiteProfile,
    image: ImageIdentity,
    runner: CommandRunner,
) -> Path:
    """Write and validate the exact runtime-only digest-bound stack.

    Args:
        root: Swarm repository root.
        profile: Validated Felix candidate profile.
        image: Resolved immutable image identity.
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
        output.write_text(_digest_bound_stack(profile, image), encoding="utf-8")
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

    secret_names = tuple(mount.name for mount in profile.secret_mounts)
    for name in secret_names:
        runner.run(["docker", "secret", "inspect", name])
    routing = profile.data["routing"]
    if not isinstance(routing, dict):
        raise FelixReleaseError("Felix routing profile is not an object.")
    network_name = str(routing["traefikNetwork"])
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
    return secret_names


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
        raise FelixReleaseError("Felix prod.env/site profile validation failed.") from exc
    _verify_swarm(runner)
    secrets = _verify_docker_resources(runner, profile)
    directories = _verify_data_directories(profile)
    image = resolve_image_identity(runner, profile)
    stack_path = write_digest_bound_stack(root, profile, image, runner)
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
            "publishedImageDigestAndPlatform": True,
            "swarmManager": True,
            "dockerSecrets": True,
            "overlayNetwork": True,
            "dataDirectories": True,
            "composeConfig": True,
            "candidateDnsTls": True,
            "keycloakDiscoveryJwks": True,
            "legacyWebAndOidcUnchanged": True,
        },
    )
