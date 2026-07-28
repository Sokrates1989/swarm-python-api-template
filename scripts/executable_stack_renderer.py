"""
Module: executable_stack_renderer.py

Description:
    Renders one deterministic Docker Swarm stack from a normalized executable
    site profile. Service inclusion, images, routing, resources, environment,
    and secret mounts are entirely site-config-driven.

Dependencies:
    - scripts/executable_profile.py.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from executable_profile import (
    ExecutableProfile,
    ExecutableProfileError,
)


_DIGEST_IMAGE_PATTERN = re.compile(r"[a-z0-9][a-z0-9._/-]*@sha256:[a-f0-9]{64}")
_MARKER_PATTERN = re.compile(r"\$\{[^}]*\}|XXX_CHANGE|###[A-Za-z0-9_]")
_DIRECT_SECRET_ENV_KEYS = frozenset(
    {
        "DB_PASSWORD",
        "KEYCLOAK_ADMIN_CLIENT_SECRET",
        "KEYCLOAK_CLIENT_SECRET",
        "PGADMIN_PASSWORD",
    }
)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    """Return a JSON object used by a validated profile.

    Args:
        value: Parsed JSON value.
        field: Diagnostic field name.

    Returns:
        Mapping value.

    Raises:
        ExecutableProfileError: If profile data was mutated after validation.
    """

    if not isinstance(value, Mapping):
        raise ExecutableProfileError(f"{field} must be a JSON object.")
    return value


def _yaml_text(value: object) -> str:
    """Render one scalar as a double-quoted YAML value.

    Args:
        value: Scalar value.

    Returns:
        JSON-compatible quoted YAML scalar.
    """

    import json

    return json.dumps(str(value), ensure_ascii=True)


def _traefik_labels(
    profile: ExecutableProfile,
    *,
    service: str,
    domain: str,
    container_port: int,
) -> list[str]:
    """Render generic Traefik labels for one public service.

    Args:
        profile: Validated deployment profile.
        service: Stable service suffix.
        domain: Public host.
        container_port: Container listener port.

    Returns:
        Indented Compose deploy-label lines.
    """

    values = profile.deployment
    if values["PROXY_TYPE"] != "traefik":
        return []
    stack = profile.stack_name
    router = f"{stack}-{service}"
    network = values["TRAEFIK_NETWORK"]
    constraint_label = values["TRAEFIK_CONSTRAINT_LABEL"]
    lines = [
        "      labels:",
        '        - "traefik.enable=true"',
        f'        - "traefik.constraint-label={constraint_label}"',
        f'        - "traefik.docker.network={network}"',
        f'        - "traefik.http.routers.{router}.service={router}"',
        f'        - "traefik.http.routers.{router}.rule=Host(`{domain}`)"',
        (
            f'        - "traefik.http.services.{router}.'
            f'loadbalancer.server.port={container_port}"'
        ),
    ]
    if values["SSL_MODE"] == "letsencrypt":
        lines.extend(
            [
                f'        - "traefik.http.routers.{router}.entrypoints=https,http,web"',
                f'        - "traefik.http.routers.{router}.tls=true"',
                (
                    f'        - "traefik.http.routers.{router}.tls.certresolver='
                    f'{values["TRAEFIK_CERT_RESOLVER"]}"'
                ),
            ]
        )
    elif values["SSL_MODE"] == "proxy":
        middleware = f"{router}-protoheader"
        lines.extend(
            [
                f'        - "traefik.http.routers.{router}.entrypoints=http"',
                (
                    f'        - "traefik.http.middlewares.{middleware}.headers.'
                    'customrequestheaders.X-Forwarded-Proto=https"'
                ),
                f'        - "traefik.http.routers.{router}.middlewares={middleware}"',
            ]
        )
    return lines


def _release_deploy_block(
    profile: ExecutableProfile,
    *,
    service: str,
    replicas: str,
    memory: str,
    domain: str,
    container_port: int,
) -> list[str]:
    """Render start-first service deployment and rollback policy.

    Args:
        profile: Validated deployment profile.
        service: Service suffix used for routing.
        replicas: Desired replicas.
        memory: Docker memory limit.
        domain: Public service domain.
        container_port: Container listener port.

    Returns:
        Indented Compose deploy lines.
    """

    return [
        "    deploy:",
        "      mode: replicated",
        f"      replicas: {replicas}",
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
        f"          memory: {_yaml_text(memory)}",
        *_traefik_labels(
            profile,
            service=service,
            domain=domain,
            container_port=container_port,
        ),
    ]


def _service_networks(profile: ExecutableProfile) -> list[str]:
    """Render backend plus optional proxy network membership.

    Args:
        profile: Validated deployment profile.

    Returns:
        Indented network lines.
    """

    lines = ["    networks:", "      - backend"]
    if profile.deployment["PROXY_TYPE"] == "traefik":
        lines.append(f"      - {_yaml_text(profile.deployment['TRAEFIK_NETWORK'])}")
    return lines


def _direct_port(
    profile: ExecutableProfile,
    *,
    container_port: int,
    published_port: str,
) -> list[str]:
    """Render one host-mode port when Traefik is disabled.

    Args:
        profile: Validated deployment profile.
        container_port: Service target port.
        published_port: Operator-selected host port.

    Returns:
        Indented port mapping lines or an empty list.
    """

    if profile.deployment["PROXY_TYPE"] != "none":
        return []
    return [
        "    ports:",
        f"      - target: {container_port}",
        f"        published: {published_port}",
        "        protocol: tcp",
        "        mode: host",
    ]


def _render_web_service(profile: ExecutableProfile) -> list[str]:
    """Render the optional selected-profile WebApp service.

    Args:
        profile: Validated deployment profile.

    Returns:
        WebApp service lines or an empty list.
    """

    values = profile.deployment
    if values["WEB_ENABLED"] != "true":
        return []
    routing = _mapping(profile.data["routing"], "routing")
    port = int(routing["webContainerPort"])
    health_path = str(routing["webHealthPath"])
    lines = [
        "  web:",
        f"    image: {_yaml_text(profile.web_image_reference)}",
        *_service_networks(profile),
        *_direct_port(
            profile,
            container_port=port,
            published_port=values["WEB_PUBLISHED_PORT"],
        ),
        "    healthcheck:",
        (
            '      test: ["CMD-SHELL", '
            f'"wget -q -O /dev/null http://127.0.0.1:{port}{health_path}"]'
        ),
        "      interval: 20s",
        "      timeout: 5s",
        "      retries: 5",
        "      start_period: 10s",
        *_release_deploy_block(
            profile,
            service="web",
            replicas=values["WEB_REPLICAS"],
            memory=values["WEB_MEMORY_LIMIT"],
            domain=values["WEB_DOMAIN"],
            container_port=port,
        ),
    ]
    return lines


def _render_redis_service(profile: ExecutableProfile) -> list[str]:
    """Render the optional digest-pinned Redis service.

    Args:
        profile: Validated deployment profile.

    Returns:
        Redis service lines or an empty list.
    """

    services = _mapping(profile.data["services"], "services")
    if services.get("redis") is not True:
        return []
    return [
        "  redis:",
        f"    image: {_yaml_text(services['redisImage'])}",
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


def _render_api_environment(profile: ExecutableProfile) -> list[str]:
    """Render only profile-authorized API environment fields.

    Args:
        profile: Validated deployment profile.

    Returns:
        Indented environment mapping lines.
    """

    mount_paths = {mount.env_key: mount.target for mount in profile.secret_mounts}
    lines = ["    environment:"]
    for key in profile.env_keys:
        value = profile.environment.get(key, mount_paths.get(key))
        if value is None:
            raise ExecutableProfileError(f"Executable envKeys value is missing: {key}")
        lines.append(f"      {key}: {_yaml_text(value)}")
    return lines


def _render_api_service(profile: ExecutableProfile) -> list[str]:
    """Render the selected profile's API service.

    Args:
        profile: Validated deployment profile.

    Returns:
        API service lines.
    """

    values = profile.deployment
    routing = _mapping(profile.data["routing"], "routing")
    port = int(routing["containerPort"])
    health_path = str(routing["healthPath"])
    lines = [
        "  api:",
        f"    image: {_yaml_text(profile.image_reference)}",
        *_service_networks(profile),
        *_direct_port(
            profile,
            container_port=port,
            published_port=values["API_PUBLISHED_PORT"],
        ),
    ]
    if profile.secret_mounts:
        lines.append("    secrets:")
        for mount in profile.secret_mounts:
            lines.extend(
                [
                    f"      - source: {_yaml_text(mount.name)}",
                    f"        target: {_yaml_text(mount.name)}",
                ]
            )
    lines.extend(
        [
            *_render_api_environment(profile),
            "    volumes:",
            f"      - {_yaml_text(values['DATA_ROOT'] + '/backups:/app/backups')}",
            f"      - {_yaml_text(values['DATA_ROOT'] + '/logs/api:/app/logs')}",
            "    healthcheck:",
            (
                '      test: ["CMD", "python", "-c", '
                f'"import urllib.request; urllib.request.urlopen('
                f"'http://localhost:{port}{health_path}').read()\"]"
            ),
            "      interval: 30s",
            "      timeout: 5s",
            "      retries: 5",
            "      start_period: 20s",
            *_release_deploy_block(
                profile,
                service="api",
                replicas=values["API_REPLICAS"],
                memory=values["MEMORY_LIMIT"],
                domain=values["DOMAIN"],
                container_port=port,
            ),
        ]
    )
    return lines


def _database_password_mount(profile: ExecutableProfile) -> tuple[str, str]:
    """Resolve the database password secret name and target.

    Args:
        profile: Validated deployment profile.

    Returns:
        Docker secret name and mounted target path.

    Raises:
        ExecutableProfileError: If no DB password mount is declared.
    """

    for mount in profile.secret_mounts:
        if mount.env_key == "DB_PASSWORD_FILE":
            return mount.name, mount.target
    raise ExecutableProfileError(
        "Local database requires a DB_PASSWORD_FILE secret mount."
    )


def _render_postgres_service(profile: ExecutableProfile) -> list[str]:
    """Render a local PostgreSQL service when selected.

    Args:
        profile: Validated deployment profile.

    Returns:
        PostgreSQL service lines or an empty list.

    Raises:
        ExecutableProfileError: If an unsupported local DB type is requested.
    """

    values = profile.deployment
    if values["DB_MODE"] != "local":
        return []
    if values["DB_TYPE"] != "postgresql":
        raise ExecutableProfileError(
            f"Executable renderer does not support local {values['DB_TYPE']} yet."
        )
    database = _mapping(profile.data["database"], "database")
    secret_name, secret_target = _database_password_mount(profile)
    return [
        "  postgres:",
        f"    image: {_yaml_text(database['image'])}",
        "    networks:",
        "      - backend",
        "    secrets:",
        f"      - source: {_yaml_text(secret_name)}",
        f"        target: {_yaml_text(secret_name)}",
        "    environment:",
        f"      POSTGRES_DB: {_yaml_text(values['DB_NAME'])}",
        f"      POSTGRES_USER: {_yaml_text(values['DB_USER'])}",
        f"      POSTGRES_PASSWORD_FILE: {_yaml_text(secret_target)}",
        "    volumes:",
        (
            "      - "
            + _yaml_text(
                values["DATA_ROOT"]
                + "/postgres_data:/var/lib/postgresql/data"
            )
        ),
        "    deploy:",
        "      mode: replicated",
        "      replicas: 1",
        "      placement:",
        "        constraints:",
        "          - node.role == manager",
        "      restart_policy:",
        "        condition: on-failure",
        "    healthcheck:",
        f'      test: ["CMD-SHELL", "pg_isready -U {values["DB_USER"]}"]',
        "      interval: 10s",
        "      timeout: 5s",
        "      retries: 10",
        "      start_period: 20s",
    ]


def _render_pgadmin_service(profile: ExecutableProfile) -> list[str]:
    """Render optional pgAdmin using profile-declared image and secret.

    Args:
        profile: Validated deployment profile.

    Returns:
        pgAdmin service lines or an empty list.
    """

    values = profile.deployment
    if values["PGADMIN_ENABLED"] != "true":
        return []
    database = _mapping(profile.data["database"], "database")
    secret = str(database["pgadminSecret"])
    port = 5050
    lines = [
        "  pgadmin:",
        f"    image: {_yaml_text(database['pgadminImage'])}",
        *_service_networks(profile),
        *_direct_port(
            profile,
            container_port=port,
            published_port=values["PGADMIN_PUBLISHED_PORT"],
        ),
        "    secrets:",
        f"      - source: {_yaml_text(secret)}",
        f"        target: {_yaml_text(secret)}",
        "    environment:",
        f"      PGADMIN_DEFAULT_EMAIL: {_yaml_text(values['PGADMIN_EMAIL'])}",
        (
            "      PGADMIN_DEFAULT_PASSWORD_FILE: "
            f"{_yaml_text('/run/secrets/' + secret)}"
        ),
        f'      PGADMIN_LISTEN_PORT: "{port}"',
        '      PGADMIN_CONFIG_SERVER_MODE: "True"',
        "    volumes:",
        f"      - {_yaml_text(values['DATA_ROOT'] + '/pgadmin:/var/lib/pgadmin')}",
        *_release_deploy_block(
            profile,
            service="pgadmin",
            replicas=values["PGADMIN_REPLICAS"],
            memory="256M",
            domain=values["PGADMIN_DOMAIN"],
            container_port=port,
        ),
    ]
    return lines


def _render_footer(profile: ExecutableProfile) -> list[str]:
    """Render networks and active external Docker secrets.

    Args:
        profile: Validated deployment profile.

    Returns:
        Top-level network and secret declarations.
    """

    values = profile.deployment
    lines = ["networks:", "  backend:", "    driver: overlay"]
    if values["PROXY_TYPE"] == "traefik":
        lines.extend(
            [
                f"  {_yaml_text(values['TRAEFIK_NETWORK'])}:",
                "    external: true",
            ]
        )
    secret_names = [mount.name for mount in profile.secret_mounts]
    if values["PGADMIN_ENABLED"] == "true":
        database = _mapping(profile.data["database"], "database")
        secret_names.append(str(database["pgadminSecret"]))
    lines.append("secrets:")
    for secret in dict.fromkeys(secret_names):
        lines.extend([f"  {_yaml_text(secret)}:", "    external: true"])
    return lines


def render_stack(profile: ExecutableProfile) -> str:
    """Render and validate one complete resolved Compose stack.

    Args:
        profile: Validated executable profile.

    Returns:
        Complete YAML ending in one newline.

    Raises:
        ExecutableProfileError: If the rendered artifact violates safeguards.
    """

    lines = [
        f"# Generated from site-configs/{profile.config_id}.json and root .env.",
        "# Secret identifiers are external references; values are never rendered.",
        "services:",
        *_render_web_service(profile),
        *_render_redis_service(profile),
        *_render_api_service(profile),
        *_render_postgres_service(profile),
        *_render_pgadmin_service(profile),
        *_render_footer(profile),
        "",
    ]
    rendered = "\n".join(lines)
    validate_rendered_stack(rendered, profile)
    return rendered


def validate_rendered_stack(
    stack: str,
    profile: ExecutableProfile,
) -> None:
    """Reject unresolved, secret-bearing, or mutable rendered artifacts.

    Args:
        stack: Rendered Compose YAML.
        profile: Validated executable profile.

    Raises:
        ExecutableProfileError: If any invariant is violated.
    """

    if _MARKER_PATTERN.search(stack):
        raise ExecutableProfileError("Rendered stack contains an unresolved marker.")
    direct_pattern = re.compile(
        r"^\s+(?:" + "|".join(sorted(_DIRECT_SECRET_ENV_KEYS)) + r")\s*:",
        re.MULTILINE,
    )
    if direct_pattern.search(stack):
        raise ExecutableProfileError("Rendered stack contains a direct secret field.")
    image_references = re.findall(
        r'^\s+image:\s+"([^"]+)"$',
        stack,
        re.MULTILINE,
    )
    mutable_release_images = {
        profile.image_reference,
        profile.web_image_reference,
    } - {""}
    for reference in image_references:
        if reference in mutable_release_images:
            continue
        if not _DIGEST_IMAGE_PATTERN.fullmatch(reference):
            raise ExecutableProfileError(
                f"Infrastructure image must be digest-pinned: {reference}"
            )


def write_stack(path: Path, content: str) -> None:
    """Atomically write one validated generated stack.

    Args:
        path: Exact stack destination.
        content: Fully validated YAML.

    Raises:
        OSError: If the temporary or destination write fails.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".swarm-stack.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def compose_check(stack_path: Path) -> None:
    """Run Docker Compose schema/interpolation validation.

    Args:
        stack_path: Fully rendered stack path.

    Raises:
        ExecutableProfileError: If Compose is unavailable or rejects the file.
    """

    try:
        completed = subprocess.run(
            ["docker", "compose", "-f", str(stack_path), "config", "--quiet"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise ExecutableProfileError("Docker Compose could not be started.") from error
    if completed.returncode != 0:
        diagnostic = (completed.stderr or completed.stdout).strip()
        raise ExecutableProfileError(
            "Docker Compose rejected the rendered stack"
            + (f": {diagnostic}" if diagnostic else ".")
        )


__all__ = [
    "compose_check",
    "render_stack",
    "validate_rendered_stack",
    "write_stack",
]
