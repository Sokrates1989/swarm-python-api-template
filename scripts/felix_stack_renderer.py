"""
Module: felix_stack_renderer.py

Description:
    Renders and validates the fully resolved, secret-free Felix Swarm Compose
    artifact from an already validated executable site profile.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from felix_site_contract import (
    _CANDIDATE_STACK,
    _DIGEST_IMAGE_PATTERN,
    _DIRECT_SECRET_ENV_KEYS,
    _MARKER_PATTERN,
    _as_mapping,
    _validate_public_https,
    FelixSiteProfile,
    FelixSiteProfileError,
    SecretMount,
)


def _yaml_text(value: object) -> str:
    """Render one deterministic YAML-compatible JSON scalar.

    Args:
        value: Scalar value converted to text.

    Returns:
        Double-quoted JSON string accepted by YAML/Compose.
    """

    return json.dumps(str(value), ensure_ascii=True)


def _render_redis_service(profile: FelixSiteProfile) -> list[str]:
    """Render the digest-pinned Redis service.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        Redis Compose lines without a top-level `services` key.
    """

    services = _as_mapping(profile.data["services"], "services")
    image = _yaml_text(services["redisImage"])
    return [
        "  redis:",
        f"    image: {image}",
        "    networks:",
        "      - backend",
        "    deploy:",
        "      mode: replicated",
        "      replicas: 1",
        "    healthcheck:",
        '      test: ["CMD", "redis-cli", "ping"]',
        "      interval: 10s",
        "      timeout: 3s",
        "      retries: 3",
    ]


def _render_api_environment(profile: FelixSiteProfile) -> list[str]:
    """Render only envKeys-authorized API environment fields.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        Indented Compose environment mapping lines.
    """

    mount_paths = {mount.env_key: mount.target for mount in profile.secret_mounts}
    lines = ["    environment:"]
    for key in profile.env_keys:
        value = profile.environment.get(key, mount_paths.get(key))
        if value is None:
            raise FelixSiteProfileError(f"Executable envKeys value is missing: {key}")
        lines.append(f"      {key}: {_yaml_text(value)}")
    return lines


def _render_api_labels(profile: FelixSiteProfile) -> list[str]:
    """Render proxy-mode-specific Traefik labels when enabled.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        Indented API label lines, or an empty list without Traefik.
    """

    values = profile.deployment
    if values["PROXY_TYPE"] != "traefik":
        return []
    stack = _CANDIDATE_STACK
    network = values["TRAEFIK_NETWORK"]
    domain = values["DOMAIN"]
    lines = [
        "      labels:",
        '        - "traefik.enable=true"',
        '        - "traefik.constraint-label=traefik-public"',
        f'        - "traefik.docker.network={network}"',
        f'        - "traefik.http.routers.{stack}-api.service={stack}-api"',
        f'        - "traefik.http.routers.{stack}-api.rule=Host(`{domain}`)"',
        f'        - "traefik.http.services.{stack}-api.loadbalancer.server.port=8080"',
    ]
    if values["SSL_MODE"] == "letsencrypt":
        lines.extend(
            [
                f'        - "traefik.http.routers.{stack}-api.entrypoints=https,http,web"',
                f'        - "traefik.http.routers.{stack}-api.tls=true"',
                f'        - "traefik.http.routers.{stack}-api.tls.certresolver=le"',
            ]
        )
    else:
        lines.extend(
            [
                f'        - "traefik.http.routers.{stack}-api.entrypoints=http"',
                (
                    f'        - "traefik.http.middlewares.{stack}-protoheader.headers.'
                    'customrequestheaders.X-Forwarded-Proto=https"'
                ),
                (
                    f'        - "traefik.http.routers.{stack}-api.middlewares='
                    f'{stack}-protoheader"'
                ),
            ]
        )
    return lines


def _render_api_deploy(profile: FelixSiteProfile) -> list[str]:
    """Render bounded start-first deployment and optional proxy labels.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        Indented API `deploy` mapping lines.
    """

    values = profile.deployment
    return [
        "    deploy:",
        "      mode: replicated",
        f"      replicas: {values['API_REPLICAS']}",
        "      update_config:",
        "        parallelism: 1",
        "        delay: 10s",
        "        failure_action: rollback",
        "        monitor: 60s",
        "        order: start-first",
        "      rollback_config:",
        "        parallelism: 1",
        "        delay: 5s",
        "        failure_action: pause",
        "        monitor: 60s",
        "        order: stop-first",
        "      restart_policy:",
        "        condition: on-failure",
        "        delay: 5s",
        "        max_attempts: 3",
        "      resources:",
        "        limits:",
        f"          memory: {_yaml_text(values['MEMORY_LIMIT'])}",
        *_render_api_labels(profile),
    ]


def _render_api_runtime(profile: FelixSiteProfile) -> list[str]:
    """Render API host volumes and internal healthcheck.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        Indented volume and healthcheck Compose lines.
    """

    data_root = profile.deployment["DATA_ROOT"]
    return [
        "    volumes:",
        f"      - {_yaml_text(data_root + '/backups:/app/backups')}",
        f"      - {_yaml_text(data_root + '/logs/api:/app/logs')}",
        "    healthcheck:",
        (
            '      test: ["CMD", "python", "-c", '
            '"import urllib.request; '
            "urllib.request.urlopen('http://localhost:8080/health').read()\"]"
        ),
        "      interval: 30s",
        "      timeout: 5s",
        "      retries: 5",
        "      start_period: 20s",
    ]


def _render_api_service(profile: FelixSiteProfile) -> list[str]:
    """Render the candidate Felix API service and exact Traefik route.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        API Compose lines without a top-level `services` key.
    """

    values = profile.deployment
    lines = [
        "  api:",
        f"    image: {_yaml_text(profile.image_reference)}",
        "    networks:",
        "      - backend",
    ]
    if values["PROXY_TYPE"] == "traefik":
        lines.append(f"      - {_yaml_text(values['TRAEFIK_NETWORK'])}")
    if values["PROXY_TYPE"] == "none":
        lines.extend(
            [
                "    ports:",
                "      - target: 8080",
                f"        published: {values['API_PUBLISHED_PORT']}",
                "        protocol: tcp",
                "        mode: host",
            ]
        )
    lines.append("    secrets:")
    for mount in profile.secret_mounts:
        lines.extend(
            [
                f"      - source: {_yaml_text(mount.name)}",
                f"        target: {_yaml_text(mount.name)}",
            ]
        )
    lines.extend(_render_api_environment(profile))
    lines.extend(_render_api_runtime(profile))
    lines.extend(_render_api_deploy(profile))
    return lines


def _render_postgres_service(profile: FelixSiteProfile) -> list[str]:
    """Render the local digest-pinned PostgreSQL service.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        PostgreSQL Compose lines without a top-level `services` key.
    """

    database = _as_mapping(profile.data["database"], "database")
    data_root = profile.deployment["DATA_ROOT"]
    db_mount = next(
        mount for mount in profile.secret_mounts if mount.env_key == "DB_PASSWORD_FILE"
    )
    return [
        "  postgres:",
        f"    image: {_yaml_text(database['image'])}",
        "    networks:",
        "      - backend",
        "    secrets:",
        f"      - source: {_yaml_text(db_mount.name)}",
        f"        target: {_yaml_text(db_mount.name)}",
        "    environment:",
        f"      POSTGRES_DB: {_yaml_text(profile.environment['DB_NAME'])}",
        f"      POSTGRES_USER: {_yaml_text(profile.environment['DB_USER'])}",
        f"      POSTGRES_PASSWORD_FILE: {_yaml_text(db_mount.target)}",
        "    volumes:",
        f"      - {_yaml_text(data_root + '/postgres_data:/var/lib/postgresql/data')}",
        "    deploy:",
        "      mode: replicated",
        "      replicas: 1",
        "      placement:",
        "        constraints:",
        "          - node.role == manager",
        "      restart_policy:",
        "        condition: on-failure",
        "    healthcheck:",
        f'      test: ["CMD-SHELL", "pg_isready -U {profile.environment["DB_USER"]}"]',
        "      interval: 10s",
        "      timeout: 5s",
        "      retries: 10",
        "      start_period: 20s",
    ]


def _render_pgadmin_labels(profile: FelixSiteProfile) -> list[str]:
    """Render the optional pgAdmin Traefik route for the selected TLS mode.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        Indented pgAdmin deployment label lines.
    """

    values = profile.deployment
    stack = _CANDIDATE_STACK
    network = values["TRAEFIK_NETWORK"]
    domain = values["PGADMIN_DOMAIN"]
    lines = [
        "      labels:",
        '        - "traefik.enable=true"',
        '        - "traefik.constraint-label=traefik-public"',
        f'        - "traefik.docker.network={network}"',
        f'        - "traefik.http.routers.{stack}-pgadmin.service={stack}-pgadmin"',
        f'        - "traefik.http.routers.{stack}-pgadmin.rule=Host(`{domain}`)"',
        (
            f'        - "traefik.http.services.{stack}-pgadmin.'
            'loadbalancer.server.port=5050"'
        ),
    ]
    if values["SSL_MODE"] == "letsencrypt":
        lines.extend(
            [
                (
                    f'        - "traefik.http.routers.{stack}-pgadmin.'
                    'entrypoints=https,http,web"'
                ),
                f'        - "traefik.http.routers.{stack}-pgadmin.tls=true"',
                (
                    f'        - "traefik.http.routers.{stack}-pgadmin.'
                    'tls.certresolver=le"'
                ),
            ]
        )
    else:
        middleware = f"{stack}-pgadmin-protoheader"
        lines.extend(
            [
                f'        - "traefik.http.routers.{stack}-pgadmin.entrypoints=http"',
                (
                    f'        - "traefik.http.middlewares.{middleware}.headers.'
                    'customrequestheaders.X-Forwarded-Proto=https"'
                ),
                (
                    f'        - "traefik.http.routers.{stack}-pgadmin.'
                    f'middlewares={middleware}"'
                ),
            ]
        )
    return lines


def _render_pgadmin_service(profile: FelixSiteProfile) -> list[str]:
    """Render optional pgAdmin with a dedicated file-backed password secret.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        pgAdmin Compose lines, or an empty list when disabled.
    """

    values = profile.deployment
    if values["PGADMIN_ENABLED"] != "true":
        return []
    database = _as_mapping(profile.data["database"], "database")
    secret = str(database["pgadminSecret"])
    data_root = values["DATA_ROOT"]
    return [
        "  pgadmin:",
        f"    image: {_yaml_text(database['pgadminImage'])}",
        "    networks:",
        "      - backend",
        f"      - {_yaml_text(values['TRAEFIK_NETWORK'])}",
        "    secrets:",
        f"      - source: {_yaml_text(secret)}",
        f"        target: {_yaml_text(secret)}",
        "    environment:",
        f"      PGADMIN_DEFAULT_EMAIL: {_yaml_text(values['PGADMIN_EMAIL'])}",
        f"      PGADMIN_DEFAULT_PASSWORD_FILE: {_yaml_text('/run/secrets/' + secret)}",
        '      PGADMIN_LISTEN_PORT: "5050"',
        '      PGADMIN_CONFIG_SERVER_MODE: "True"',
        "    volumes:",
        f"      - {_yaml_text(data_root + '/pgadmin:/var/lib/pgadmin')}",
        "    deploy:",
        "      mode: replicated",
        f"      replicas: {values['PGADMIN_REPLICAS']}",
        "      restart_policy:",
        "        condition: on-failure",
        "        delay: 5s",
        "      placement:",
        "        constraints:",
        "          - node.role == manager",
        "      resources:",
        "        limits:",
        '          memory: "256M"',
        *_render_pgadmin_labels(profile),
    ]


def _render_footer(profile: FelixSiteProfile) -> list[str]:
    """Render networks and active external Docker secret declarations.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        Top-level Compose network and secret lines.
    """

    values = profile.deployment
    lines = [
        "networks:",
        "  backend:",
        "    driver: overlay",
    ]
    if values["PROXY_TYPE"] == "traefik":
        lines.extend(
            [
                f"  {_yaml_text(values['TRAEFIK_NETWORK'])}:",
                "    external: true",
            ]
        )
    lines.append("secrets:")
    for mount in profile.secret_mounts:
        lines.extend(
            [
                f"  {_yaml_text(mount.name)}:",
                "    external: true",
            ]
        )
    if values["PGADMIN_ENABLED"] == "true":
        database = _as_mapping(profile.data["database"], "database")
        lines.extend(
            [
                f"  {_yaml_text(database['pgadminSecret'])}:",
                "    external: true",
            ]
        )
    return lines


def render_stack(profile: FelixSiteProfile) -> str:
    """Render the fully resolved deterministic Felix Compose stack.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        Complete secret-free Compose YAML ending in one newline.

    Raises:
        FelixSiteProfileError: If an executable environment field unexpectedly
            lacks a value.
    """

    if profile.deployment["WEB_ENABLED"] == "true":
        raise FelixSiteProfileError(
            "WebApp rendering remains deferred until its immutable image slice."
        )
    lines = [
        "# Generated from site-configs/felix.json and validated root .env.",
        "# Secret identifiers are external references; no secret values are rendered.",
        "services:",
        *_render_redis_service(profile),
        *_render_api_service(profile),
        *(
            _render_postgres_service(profile)
            if profile.deployment["DB_MODE"] == "local"
            else []
        ),
        *_render_pgadmin_service(profile),
        *_render_footer(profile),
        "",
    ]
    rendered = "\n".join(lines)
    validate_rendered_stack(rendered, profile)
    return rendered


def validate_rendered_stack(stack: str, profile: FelixSiteProfile) -> None:
    """Validate an exact resolved Felix Compose artifact.

    Args:
        stack: Candidate Compose YAML.
        profile: Validated executable Felix profile.

    Returns:
        None when the stack exactly matches profile-driven rendering.

    Raises:
        FelixSiteProfileError: If the artifact drifts, contains unresolved
            markers, mutable/unversioned images, direct secrets, wildcard CORS,
            or unexpected local public configuration.
    """

    if _MARKER_PATTERN.search(stack):
        raise FelixSiteProfileError("Rendered stack contains an unresolved marker.")
    if "CORS_ORIGINS: \"*\"" in stack or "CORS_ORIGINS: '*'" in stack:
        raise FelixSiteProfileError("Rendered stack contains wildcard CORS.")
    _validate_stack_public_endpoints(stack)
    direct_pattern = re.compile(
        r"^\s+(?:" + "|".join(sorted(_DIRECT_SECRET_ENV_KEYS)) + r")\s*:",
        re.MULTILINE,
    )
    if direct_pattern.search(stack):
        raise FelixSiteProfileError("Rendered stack contains a direct secret field.")
    image_references = re.findall(r"^\s+image:\s+\"([^\"]+)\"$", stack, re.MULTILINE)
    expected_image_count = 3 if profile.deployment["DB_MODE"] == "local" else 2
    if profile.deployment["PGADMIN_ENABLED"] == "true":
        expected_image_count += 1
    if len(image_references) != expected_image_count:
        raise FelixSiteProfileError(
            f"Rendered stack must contain exactly {expected_image_count} images."
        )
    for reference in image_references:
        if reference == profile.image_reference:
            continue
        if not _DIGEST_IMAGE_PATTERN.fullmatch(reference):
            raise FelixSiteProfileError(f"Rendered service image is mutable: {reference}")


def _validate_stack_public_endpoints(stack: str) -> None:
    """Reject local, wildcard, or non-HTTPS public API environment URLs.

    Args:
        stack: Candidate rendered Compose YAML.

    Returns:
        None when all public runtime endpoints remain production-safe.

    Raises:
        FelixSiteProfileError: If a public endpoint is local or malformed.
    """

    public_fields = {
        "CORS_ORIGINS",
        "KEYCLOAK_ISSUER_URL",
        "KEYCLOAK_JWKS_URL",
        "KEYCLOAK_SERVER_URL",
    }
    pattern = re.compile(
        r"^\s+(" + "|".join(sorted(public_fields)) + r"):\s+\"([^\"]+)\"$",
        re.MULTILINE,
    )
    for field, raw_value in pattern.findall(stack):
        for value in raw_value.split(","):
            _validate_public_https(value, f"rendered {field}")


def _write_stack(path: Path, content: str) -> None:
    """Atomically write one validated generated stack.

    Args:
        path: Exact root `swarm-stack.yml` destination.
        content: Fully validated Compose YAML.

    Returns:
        None.

    Raises:
        OSError: If the temporary or destination file cannot be written.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".swarm-stack.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _resolve_root_artifact(root: Path, requested: Path | None, name: str) -> Path:
    """Resolve one CLI artifact while forbidding writes outside the root.

    Args:
        root: Resolved Swarm repository root.
        requested: Optional user-supplied path.
        name: Required root artifact filename.

    Returns:
        Exact resolved root artifact path.

    Raises:
        FelixSiteProfileError: If an override escapes or renames the artifact.
    """

    expected = (root / name).resolve()
    if requested is None:
        return expected
    candidate = (requested if requested.is_absolute() else root / requested).resolve()
    if candidate != expected:
        raise FelixSiteProfileError(f"Artifact path must resolve to {expected}.")
    return expected


def _compose_check(stack_path: Path) -> None:
    """Run Docker Compose schema/interpolation validation.

    Args:
        stack_path: Already-rendered secret-free root Compose artifact.

    Returns:
        None when `docker compose config --quiet` succeeds.

    Raises:
        FelixSiteProfileError: If Docker/Compose is unavailable or rejects the
            resolved stack.
    """

    try:
        completed = subprocess.run(
            ["docker", "compose", "-f", str(stack_path), "config", "--quiet"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise FelixSiteProfileError("Docker Compose could not be started.") from error
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout).strip()
        raise FelixSiteProfileError(
            "Docker Compose rejected the resolved stack"
            + (f": {diagnostic}" if diagnostic else ".")
        )
