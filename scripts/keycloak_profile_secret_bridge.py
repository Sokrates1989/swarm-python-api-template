"""
Module: keycloak_profile_secret_bridge.py

Description:
    Transfers one Keycloak confidential-client secret from process memory to
    its profile-declared Docker Swarm secret. Secret values are supplied only
    on standard input and are never printed, persisted, or placed in command
    arguments.

Dependencies:
    - Python standard library.
    - Docker CLI on the Swarm manager.
"""

from __future__ import annotations

import subprocess
import uuid
from typing import Protocol


class KeycloakSecretBridgeError(RuntimeError):
    """Report a Docker secret or stack precondition failure."""


class _Profile(Protocol):
    """Describe active profile state required by the Docker bridge."""

    stack_name: str


class _Identity(Protocol):
    """Describe Keycloak identity state required by the Docker bridge."""

    docker_secret: str


def _docker(
    arguments: list[str],
    *,
    input_value: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    """Run Docker without exposing a secret in arguments or output.

    Args:
        arguments: Docker CLI arguments excluding the executable.
        input_value: Optional secret supplied only on standard input.
        check: Raise when Docker exits nonzero.

    Returns:
        Completed subprocess.

    Raises:
        KeycloakSecretBridgeError: If Docker is unavailable or fails.
    """

    try:
        result = subprocess.run(
            ["docker", *arguments],
            input=None if input_value is None else input_value.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        raise KeycloakSecretBridgeError(
            "Docker CLI is unavailable."
        ) from error
    if check and result.returncode != 0:
        safe_command = " ".join(arguments[:3])
        raise KeycloakSecretBridgeError(
            f"Docker command failed: docker {safe_command}."
        )
    return result


def docker_secret_exists(secret_name: str) -> bool:
    """Check whether one Docker secret exists without reading its value.

    Args:
        secret_name: Exact profile-declared secret name.

    Returns:
        Whether Docker reports the secret.

    Raises:
        KeycloakSecretBridgeError: If Docker cannot reliably distinguish an
            absent secret from an unavailable or unauthorized Swarm manager.
    """

    result = _docker(["secret", "inspect", secret_name], check=False)
    if result.returncode == 0:
        return True
    diagnostic = b"\n".join((result.stdout, result.stderr)).decode(
        "utf-8",
        errors="replace",
    ).lower()
    missing_markers = (
        "no such secret",
        f"secret {secret_name.lower()} not found",
        f"secret '{secret_name.lower()}' not found",
    )
    if any(marker in diagnostic for marker in missing_markers):
        return False
    raise KeycloakSecretBridgeError(
        "Unable to inspect Docker secrets. Run this action on an authorized "
        "Docker Swarm manager."
    )


def stack_is_running(stack_name: str) -> bool:
    """Check whether the selected profile's stack currently exists.

    Args:
        stack_name: Exact profile-declared stack name.

    Returns:
        Whether Docker lists the stack.

    Raises:
        KeycloakSecretBridgeError: If Docker cannot list Swarm stacks.
    """

    result = _docker(
        ["stack", "ls", "--format", "{{.Name}}"],
        check=False,
    )
    if result.returncode != 0:
        raise KeycloakSecretBridgeError(
            "Unable to list Docker Swarm stacks."
        )
    names = result.stdout.decode("utf-8", errors="replace").splitlines()
    return stack_name in names


def _replace_existing_secret(
    identity: _Identity,
    secret: str,
) -> None:
    """Replace an immutable Docker secret with staged recovery material.

    Args:
        identity: Profile-derived Docker secret identity.
        secret: Newly proven Keycloak credential held only in memory.

    Returns:
        Nothing after the target is replaced and staging is removed.

    Raises:
        KeycloakSecretBridgeError: If staging, replacement, or cleanup fails.
            A failed replacement intentionally retains the named staging
            secret so the proven credential is not irrecoverably lost.
    """

    staging_name = f"keycloak_rotation_{uuid.uuid4().hex[:16]}"
    _docker(
        ["secret", "create", staging_name, "-"],
        input_value=secret,
    )
    try:
        _docker(["secret", "rm", identity.docker_secret])
        _docker(
            ["secret", "create", identity.docker_secret, "-"],
            input_value=secret,
        )
    except KeycloakSecretBridgeError as error:
        raise KeycloakSecretBridgeError(
            "Docker could not finish the Keycloak secret replacement. "
            f"Recovery secret {staging_name!r} retains the proven new "
            "credential; keep it until the target secret is restored."
        ) from error
    cleanup = _docker(["secret", "rm", staging_name], check=False)
    if cleanup.returncode != 0:
        raise KeycloakSecretBridgeError(
            "The Keycloak Docker secret was replaced, but recovery secret "
            f"{staging_name!r} could not be removed. Remove it manually."
        )


def write_docker_secret(
    profile: _Profile,
    identity: _Identity,
    secret: str,
    *,
    replace: bool,
) -> str:
    """Create or deliberately replace the declared Docker client secret.

    Args:
        profile: Active executable profile.
        identity: Profile-derived Keycloak identity.
        secret: Confidential client secret held only in memory.
        replace: Replace an existing Docker secret when true.

    Returns:
        ``created``, ``present-unverified``, or ``replaced``. Docker Swarm
        deliberately does not expose an existing secret value for comparison.

    Raises:
        KeycloakSecretBridgeError: If replacement is requested while the stack
            is running or Docker secret operations fail.
    """

    exists = docker_secret_exists(identity.docker_secret)
    if exists and not replace:
        return "present-unverified"
    if exists and stack_is_running(profile.stack_name):
        raise KeycloakSecretBridgeError(
            "Stop the selected stack before replacing its Keycloak "
            "Docker secret."
        )
    if exists:
        _replace_existing_secret(identity, secret)
        return "replaced"
    _docker(
        ["secret", "create", identity.docker_secret, "-"],
        input_value=secret,
    )
    return "created"


__all__ = [
    "KeycloakSecretBridgeError",
    "docker_secret_exists",
    "stack_is_running",
    "write_docker_secret",
]
