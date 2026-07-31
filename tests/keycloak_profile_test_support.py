"""
Module: keycloak_profile_test_support.py

Description:
    Provides reusable request-recording Keycloak Admin client support for
    profile reconciliation and verification tests.

Dependencies:
    - Python standard library only.
"""

from __future__ import annotations

from typing import Any, Callable

from keycloak_profile_client import KeycloakIdentity


class RecordingAdminClient:
    """Provide deterministic Keycloak Admin responses and request evidence."""

    def __init__(
        self,
        identity: KeycloakIdentity,
        handler: Callable[..., tuple[int, Any]],
    ) -> None:
        """Create one request-recording fake client.

        Args:
            identity: Profile-derived Keycloak identity.
            handler: Callable returning ``(status, payload)`` for a request.

        Returns:
            Nothing.
        """

        self.identity = identity
        self.handler = handler
        self.requests: list[tuple[str, str, Any, Any]] = []

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
        query: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> tuple[int, Any]:
        """Record and dispatch one fake Admin API request.

        Args:
            method: HTTP method.
            path: Admin API path.
            body: Optional JSON-compatible body.
            query: Optional query mapping.
            expected: Accepted status codes.

        Returns:
            Handler-provided status and payload.
        """

        self.requests.append((method, path, body, query))
        return self.handler(method, path, body, query, expected)


__all__ = ["RecordingAdminClient"]
