"""
Module: keycloak_profile_admin_session.py

Description:
    Models the short-lived Keycloak administrator access/refresh-token pair.
    Token values remain process-memory-only and are never rendered, logged, or
    persisted to deployment configuration.

Dependencies:
    - Python standard library.
    - scripts/keycloak_profile_errors.py.
    - scripts/keycloak_profile_http.py.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from keycloak_profile_errors import KeycloakProfileError
from keycloak_profile_http import read_keycloak_http


TOKEN_REFRESH_SKEW_SECONDS = 15.0
ADMIN_TOKEN_PATH = "/realms/master/protocol/openid-connect/token"
TokenTrace = Callable[[str, str, int], None]


def _token_lifetime(payload: Mapping[str, object], key: str) -> float:
    """Read a non-negative token lifetime from one OIDC response.

    Args:
        payload: Decoded token response.
        key: OIDC lifetime field such as ``expires_in``.

    Returns:
        Lifetime in seconds, or zero when Keycloak omitted the optional field.

    Raises:
        KeycloakProfileError: If a supplied lifetime is not non-negative
            numeric data.
    """

    value = payload.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise KeycloakProfileError(
            f"Keycloak admin token response contained invalid {key}."
        )
    if value < 0:
        raise KeycloakProfileError(
            f"Keycloak admin token response contained invalid {key}."
        )
    return float(value)


@dataclass(frozen=True)
class AdminTokenSession:
    """Hold one administrator token pair and monotonic expiry evidence.

    Attributes:
        access_token: Short-lived bearer token.
        refresh_token: Optional refresh token used without retaining the
            administrator password.
        access_expires_at: Monotonic deadline, or zero when unspecified.
        refresh_expires_at: Monotonic refresh deadline, or zero when
            unspecified.
    """

    access_token: str
    refresh_token: str
    access_expires_at: float
    refresh_expires_at: float

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, object],
        *,
        previous_refresh_token: str = "",
        clock: Callable[[], float] = time.monotonic,
    ) -> "AdminTokenSession":
        """Validate an OIDC token response and calculate expiry deadlines.

        Args:
            payload: Decoded Keycloak token response.
            previous_refresh_token: Existing process-memory refresh token kept
                when a valid refresh response does not rotate it.
            clock: Monotonic clock dependency used by deterministic tests.

        Returns:
            Validated immutable administrator session.

        Raises:
            KeycloakProfileError: If token fields or lifetimes are malformed.
        """

        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise KeycloakProfileError(
                "Keycloak admin token response did not contain an access token."
            )
        raw_refresh = payload.get("refresh_token", previous_refresh_token)
        if not isinstance(raw_refresh, str):
            raise KeycloakProfileError(
                "Keycloak admin token response contained an invalid refresh token."
            )
        now = clock()
        access_lifetime = _token_lifetime(payload, "expires_in")
        refresh_lifetime = _token_lifetime(
            payload,
            "refresh_expires_in",
        )
        return cls(
            access_token=access_token,
            refresh_token=raw_refresh,
            access_expires_at=(now + access_lifetime if access_lifetime else 0),
            refresh_expires_at=(
                now + refresh_lifetime if refresh_lifetime else 0
            ),
        )

    def access_needs_refresh(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> bool:
        """Check whether the access token is inside the refresh safety window.

        Args:
            clock: Monotonic clock dependency used by deterministic tests.

        Returns:
            ``True`` when a known access-token deadline is near or elapsed.
        """

        return bool(
            self.access_expires_at
            and clock()
            >= self.access_expires_at - TOKEN_REFRESH_SKEW_SECONDS
        )

    def can_refresh(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> bool:
        """Check whether a usable process-memory refresh token remains.

        Args:
            clock: Monotonic clock dependency used by deterministic tests.

        Returns:
            Whether a refresh token exists and has no known expired deadline.
        """

        return bool(
            self.refresh_token
            and (
                not self.refresh_expires_at
                or clock() < self.refresh_expires_at
            )
        )


class AdminSessionManager:
    """Own administrator token acquisition and password-free refresh.

    Attributes:
        server_url: Profile-declared Keycloak origin.
        session: Current process-memory token pair.
        trace: Callback receiving only method, public path, and HTTP status.
    """

    def __init__(
        self,
        server_url: str,
        session: AdminTokenSession,
        trace: TokenTrace,
    ) -> None:
        """Initialize one already authenticated administrator session.

        Args:
            server_url: Profile-declared Keycloak origin.
            session: Validated process-memory token pair.
            trace: Secret-safe token-endpoint trace callback.
        """

        self.server_url = server_url
        self.session = session
        self.trace = trace

    @classmethod
    def authenticate(
        cls,
        server_url: str,
        username: str,
        password: str,
        trace: TokenTrace,
    ) -> "AdminSessionManager":
        """Authenticate with a password that is not retained afterward.

        Args:
            server_url: Profile-declared Keycloak origin.
            username: Existing administrator username.
            password: Hidden administrator password.
            trace: Secret-safe token-endpoint trace callback.

        Returns:
            Authenticated session manager holding only token values.

        Raises:
            KeycloakProfileError: If Keycloak rejects or malforms the response.
        """

        manager = cls.__new__(cls)
        manager.server_url = server_url
        manager.trace = trace
        manager.session = manager._request(
            {
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": username,
                "password": password,
            },
            action="authenticate with Keycloak",
        )
        return manager

    @property
    def access_token(self) -> str:
        """Return the current process-memory administrator access token."""

        return self.session.access_token

    def needs_refresh(self) -> bool:
        """Return whether the access token is inside its refresh window."""

        return self.session.access_needs_refresh()

    def refresh(self) -> None:
        """Replace the access token through the in-memory refresh grant.

        Returns:
            Nothing after installing a validated token response.

        Raises:
            KeycloakProfileError: If no usable refresh token remains or the
                server rejects the refresh grant.
        """

        if not self.session.can_refresh():
            raise KeycloakProfileError(
                "The Keycloak administrator session expired during the "
                "guided bootstrap and no usable refresh token remains. "
                "Restart bootstrap and authenticate again."
            )
        try:
            self.session = self._request(
                {
                    "grant_type": "refresh_token",
                    "client_id": "admin-cli",
                    "refresh_token": self.session.refresh_token,
                },
                action="refresh the Keycloak administrator session",
                previous_refresh_token=self.session.refresh_token,
            )
        except KeycloakProfileError as error:
            raise KeycloakProfileError(
                "Automatic Keycloak administrator-session refresh failed. "
                "Restart bootstrap and authenticate again. "
                f"Cause: {error}"
            ) from error

    def _request(
        self,
        form_values: Mapping[str, str],
        *,
        action: str,
        previous_refresh_token: str = "",
    ) -> AdminTokenSession:
        """Send one password/refresh token request without tracing values.

        Args:
            form_values: OIDC form fields sent only in the request body.
            action: Secret-safe failure description.
            previous_refresh_token: Existing token retained if not rotated.

        Returns:
            Validated administrator token session.

        Raises:
            KeycloakProfileError: If transport, status, JSON, or token fields
                are invalid.
        """

        request = urllib.request.Request(
            f"{self.server_url}{ADMIN_TOKEN_PATH}",
            data=urllib.parse.urlencode(form_values).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        status, raw = read_keycloak_http(request)
        self.trace("POST", ADMIN_TOKEN_PATH, status)
        if status != 200:
            raise KeycloakProfileError(
                f"Keycloak refused to {action} (HTTP {status})."
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise KeycloakProfileError(
                f"Keycloak returned invalid JSON while trying to {action}."
            ) from error
        if not isinstance(payload, dict):
            raise KeycloakProfileError(
                f"Keycloak returned an unexpected response while trying to {action}."
            )
        return AdminTokenSession.from_payload(
            payload,
            previous_refresh_token=previous_refresh_token,
        )


__all__ = [
    "ADMIN_TOKEN_PATH",
    "AdminSessionManager",
    "AdminTokenSession",
    "TOKEN_REFRESH_SKEW_SECONDS",
]
