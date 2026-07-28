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
    """

    return (
        _docker(["secret", "inspect", secret_name], check=False).returncode
        == 0
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
        ``created``, ``kept``, or ``replaced``.

    Raises:
        KeycloakSecretBridgeError: If replacement is requested while the stack
            is running or Docker secret operations fail.
    """

    exists = docker_secret_exists(identity.docker_secret)
    if exists and not replace:
        return "kept"
    if exists and stack_is_running(profile.stack_name):
        raise KeycloakSecretBridgeError(
            "Stop the selected stack before replacing its Keycloak "
            "Docker secret."
        )
    if exists:
        _docker(["secret", "rm", identity.docker_secret])
    _docker(
        ["secret", "create", identity.docker_secret, "-"],
        input_value=secret,
    )
    return "replaced" if exists else "created"


__all__ = [
    "KeycloakSecretBridgeError",
    "docker_secret_exists",
    "stack_is_running",
    "write_docker_secret",
]
