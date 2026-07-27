"""
Module: felix_web_stack.py

Description:
    Renders the candidate Felix WebApp service and its independent Traefik or
    externally terminated public route for the unified Swarm stack.

Dependencies:
    - scripts/felix_site_contract.py.
"""

from __future__ import annotations

import json

from felix_site_contract import _CANDIDATE_STACK, FelixSiteProfile


def web_image_reference(profile: FelixSiteProfile) -> str:
    """Build the selected semantic-version WebApp image reference.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        Repository and version selected by the guided root `.env`.
    """

    values = profile.deployment
    return f"{values['WEB_IMAGE_NAME']}:{values['WEB_IMAGE_VERSION']}"


def _yaml_text(value: object) -> str:
    """Render one deterministic YAML-compatible quoted scalar.

    Args:
        value: Scalar converted to text.

    Returns:
        JSON-quoted text accepted by Compose YAML.
    """

    return json.dumps(str(value), ensure_ascii=True)


def _render_web_labels(profile: FelixSiteProfile) -> list[str]:
    """Render the WebApp router labels for the selected TLS ownership mode.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        Indented WebApp deployment label lines.
    """

    values = profile.deployment
    stack = _CANDIDATE_STACK
    network = values["TRAEFIK_NETWORK"]
    domain = values["WEB_DOMAIN"]
    lines = [
        "      labels:",
        '        - "traefik.enable=true"',
        '        - "traefik.constraint-label=traefik-public"',
        f'        - "traefik.docker.network={network}"',
        f'        - "traefik.http.routers.{stack}-web.service={stack}-web"',
        f'        - "traefik.http.routers.{stack}-web.rule=Host(`{domain}`)"',
        f'        - "traefik.http.services.{stack}-web.loadbalancer.server.port=80"',
    ]
    if values["SSL_MODE"] == "letsencrypt":
        lines.extend(
            [
                f'        - "traefik.http.routers.{stack}-web.entrypoints=https,http,web"',
                f'        - "traefik.http.routers.{stack}-web.tls=true"',
                f'        - "traefik.http.routers.{stack}-web.tls.certresolver=le"',
            ]
        )
    else:
        middleware = f"{stack}-web-protoheader"
        lines.extend(
            [
                f'        - "traefik.http.routers.{stack}-web.entrypoints=http"',
                (
                    f'        - "traefik.http.middlewares.{middleware}.headers.'
                    'customrequestheaders.X-Forwarded-Proto=https"'
                ),
                (
                    f'        - "traefik.http.routers.{stack}-web.'
                    f'middlewares={middleware}"'
                ),
            ]
        )
    return lines


def _render_web_deploy(profile: FelixSiteProfile) -> list[str]:
    """Render bounded WebApp rollout, rollback, and resource policy.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        Indented WebApp `deploy` mapping lines.
    """

    values = profile.deployment
    lines = [
        "    deploy:",
        "      mode: replicated",
        f"      replicas: {values['WEB_REPLICAS']}",
        "      update_config:",
        "        parallelism: 1",
        "        delay: 10s",
        "        failure_action: rollback",
        "        monitor: 45s",
        "        order: start-first",
        "      rollback_config:",
        "        parallelism: 1",
        "        delay: 5s",
        "        failure_action: pause",
        "        monitor: 45s",
        "        order: stop-first",
        "      restart_policy:",
        "        condition: on-failure",
        "        delay: 5s",
        "        max_attempts: 3",
        "      resources:",
        "        limits:",
        f"          memory: {_yaml_text(values['WEB_MEMORY_LIMIT'])}",
    ]
    if values["PROXY_TYPE"] == "traefik":
        lines.extend(_render_web_labels(profile))
    return lines


def render_web_service(profile: FelixSiteProfile) -> list[str]:
    """Render the required Felix WebApp service and public route.

    Args:
        profile: Validated executable Felix profile.

    Returns:
        WebApp Compose lines without a top-level `services` key.
    """

    values = profile.deployment
    lines = [
        "  web:",
        f"    image: {_yaml_text(web_image_reference(profile))}",
        "    networks:",
        "      - backend",
    ]
    if values["PROXY_TYPE"] == "traefik":
        lines.append(f"      - {_yaml_text(values['TRAEFIK_NETWORK'])}")
    else:
        lines.extend(
            [
                "    ports:",
                "      - target: 80",
                f"        published: {values['WEB_PUBLISHED_PORT']}",
                "        protocol: tcp",
                "        mode: host",
            ]
        )
    lines.extend(
        [
            "    healthcheck:",
            '      test: ["CMD", "wget", "-q", "--spider", "http://localhost/health"]',
            "      interval: 20s",
            "      timeout: 5s",
            "      retries: 5",
            "      start_period: 10s",
            *_render_web_deploy(profile),
        ]
    )
    return lines
