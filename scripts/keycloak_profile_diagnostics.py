"""
Module: keycloak_profile_diagnostics.py

Description:
    Prints secret-safe, phase-aware recovery guidance after Keycloak bootstrap
    failures. It never includes response bodies, credentials, tokens, or
    client-secret values.

Dependencies:
    - Python standard library.
"""

from __future__ import annotations

import sys
from typing import TextIO


def print_keycloak_failure_diagnostics(
    error: Exception,
    phase: str,
    *,
    stream: TextIO | None = None,
) -> None:
    """Print sanitized troubleshooting guidance for one failed phase.

    Args:
        error: Already sanitized operator-facing exception.
        phase: Bootstrap phase active when the exception escaped.
        stream: Optional destination; runtime stderr is used when omitted.

    Returns:
        Nothing.
    """

    message = str(error)
    destination = stream or sys.stderr
    print(f"[DIAGNOSTIC] Failed phase: {phase}", file=destination)
    if "HTTP 401" in message or "session expired" in message.lower():
        print(
            "[DIAGNOSTIC] Authentication succeeded earlier, but Keycloak "
            "rejected the administrator session.",
            file=destination,
        )
        print(
            "[DIAGNOSTIC] Automatic refresh/retry was attempted when a "
            "usable refresh token was available.",
            file=destination,
        )
        print(
            "[HINT] Restart bootstrap and authenticate again if the master-"
            "realm session or administrator permissions changed.",
            file=destination,
        )
    elif "HTTP 403" in message:
        print(
            "[HINT] Verify that this account still has the required "
            "master-realm administration permissions.",
            file=destination,
        )
    elif "Unable to reach Keycloak" in message:
        print(
            "[HINT] Verify DNS/TLS reachability and the existing Keycloak "
            "service state before retrying.",
            file=destination,
        )
    if "HTTP 5" in message or "HTTP 401" in message or "HTTP 403" in message:
        print(
            "[HINT] If the Admin API result remains unexplained, inspect the "
            "existing Keycloak deployment logs.",
            file=destination,
        )
        print(
            "[HINT] From its deployment checkout (for example "
            "/swarm/administration/keycloak), run ./quick-start.sh and choose "
            "View service logs.",
            file=destination,
        )
        print(
            "[HINT] Or run: docker stack services <keycloak-stack>",
            file=destination,
        )
        print(
            "[HINT] Then: docker service logs --since 10m "
            "<keycloak-service>",
            file=destination,
        )


__all__ = ["print_keycloak_failure_diagnostics"]
