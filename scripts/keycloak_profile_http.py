"""
Module: keycloak_profile_http.py

Description:
    Sends Keycloak HTTP requests through a no-redirect standard-library
    transport. Refusing redirects ensures credentials and bearer tokens never
    leave the profile-declared Keycloak origin.

Dependencies:
    - Python standard library.
    - scripts/keycloak_profile_errors.py.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

from keycloak_profile_errors import KeycloakProfileError


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so credentials never leave the declared server."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        """Decline one redirect response.

        Args:
            request: Original urllib request.
            file_pointer: Response stream supplied by urllib.
            code: HTTP redirect status.
            message: HTTP status text.
            headers: Redirect response headers.
            new_url: Proposed redirect target.

        Returns:
            Always ``None``, causing urllib to surface the redirect status.
        """

        return None


def read_keycloak_http(
    request: urllib.request.Request,
) -> tuple[int, bytes]:
    """Send one request without redirects and return status plus raw body.

    Args:
        request: Prepared urllib request.

    Returns:
        HTTP status and response bytes, including HTTP error responses.

    Raises:
        KeycloakProfileError: If the configured Keycloak server is
            unreachable or times out.
    """

    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=30) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as error:
        return int(error.code), error.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise KeycloakProfileError("Unable to reach Keycloak.") from error


__all__ = ["read_keycloak_http"]
