"""
Module: keycloak_profile_errors.py

Description:
    Defines the shared secret-safe exception boundary for profile-driven
    Keycloak HTTP, authentication, planning, and reconciliation modules.

Dependencies:
    - Python standard library.
"""


class KeycloakProfileError(RuntimeError):
    """Report a secret-safe, operator-facing Keycloak workflow failure."""


__all__ = ["KeycloakProfileError"]
