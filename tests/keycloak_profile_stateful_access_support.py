"""
Module: keycloak_profile_stateful_access_support.py

Description:
    Models the application realm-role and temporary test-user Admin API
    resources used by the stateful Keycloak bootstrap integration fake. The
    fake records only whether a password was set and never retains its value.

Dependencies:
    - Python standard library only.
"""

from __future__ import annotations

import copy
import urllib.parse
from typing import Any, Protocol


Response = tuple[int, Any]


class _Identity(Protocol):
    """Describe identity values needed by the focused access fake."""

    realm: str


class StatefulApplicationAccess:
    """Model mutable realm roles, test users, passwords, and role mappings."""

    def __init__(self, identity: _Identity) -> None:
        """Create empty application-access state.

        Args:
            identity: Active Keycloak identity.

        Returns:
            Nothing.
        """

        self.identity = identity
        self.realm_roles: dict[str, dict[str, Any]] = {}
        self.users: dict[str, dict[str, Any]] = {}
        self.user_roles: dict[str, set[str]] = {}
        self.passwords_set: set[str] = set()

    @property
    def realm_root(self) -> str:
        """Return the selected realm Admin API root.

        Returns:
            Escaped realm path.
        """

        realm = urllib.parse.quote(self.identity.realm, safe="")
        return f"/admin/realms/{realm}"

    def handle(
        self,
        method: str,
        path: str,
        body: Any,
        query: dict[str, str] | None,
    ) -> Response | None:
        """Dispatch one application role or test-user request.

        Args:
            method: HTTP method.
            path: Admin API path.
            body: Optional request body.
            query: Optional query mapping.

        Returns:
            Fake response or ``None`` for an unrelated route.
        """

        handlers = (
            self._handle_roles,
            self._handle_user_collection,
            self._handle_user_resource,
        )
        for handler in handlers:
            response = handler(method, path, body, query)
            if response is not None:
                return response
        return None

    def _handle_roles(
        self,
        method: str,
        path: str,
        body: Any,
        query: dict[str, str] | None,
    ) -> Response | None:
        """Read, create, or update application realm roles.

        Args:
            method: HTTP method.
            path: Admin API path.
            body: Optional role representation.
            query: Optional query, which must be absent.

        Returns:
            Role response or ``None`` for another route.
        """

        if query is not None:
            return None
        roles_root = f"{self.realm_root}/roles"
        if path == roles_root and method == "POST":
            role = self._mapping(body, "role create")
            name = str(role["name"])
            role.setdefault("id", f"realm-role-{name}")
            self.realm_roles[name] = role
            return 201, None
        prefix = f"{roles_root}/"
        if not path.startswith(prefix):
            return None
        name = urllib.parse.unquote(path[len(prefix) :])
        current = self.realm_roles.get(name)
        if method == "GET":
            return (404, None) if current is None else (200, current)
        if method == "PUT" and current is not None:
            role = self._mapping(body, "role update")
            role.setdefault("id", current["id"])
            self.realm_roles[name] = role
            return 204, None
        return None

    def _handle_user_collection(
        self,
        method: str,
        path: str,
        body: Any,
        query: dict[str, str] | None,
    ) -> Response | None:
        """Resolve or create exact test users.

        Args:
            method: HTTP method.
            path: Admin API path.
            body: Optional user representation.
            query: Optional exact username query.

        Returns:
            User collection response or ``None`` for another route.
        """

        users_root = f"{self.realm_root}/users"
        if path != users_root:
            return None
        if method == "GET" and query is not None:
            username = str(query.get("username", ""))
            current = self.users.get(username)
            return 200, [] if current is None else [current]
        if method == "POST" and query is None:
            user = self._mapping(body, "user create")
            username = str(user["username"])
            user["id"] = f"user-{username}"
            self.users[username] = user
            self.user_roles[user["id"]] = set()
            return 201, None
        return None

    def _handle_user_resource(
        self,
        method: str,
        path: str,
        body: Any,
        query: dict[str, str] | None,
    ) -> Response | None:
        """Update users, set passwords, and reconcile realm-role mappings.

        Args:
            method: HTTP method.
            path: Admin API path.
            body: Optional user, credential, or role list.
            query: Optional query, which must be absent.

        Returns:
            User-resource response or ``None`` for another route.
        """

        if query is not None:
            return None
        for username, current in self.users.items():
            root = f"{self.realm_root}/users/{current['id']}"
            if path == root and method == "PUT":
                replacement = self._mapping(body, "user update")
                replacement["id"] = current["id"]
                self.users[username] = replacement
                return 204, None
            if path == f"{root}/reset-password" and method == "PUT":
                credential = self._mapping(body, "password reset")
                if not credential.get("value"):
                    raise AssertionError("Password reset value must not be empty.")
                self.passwords_set.add(username)
                return 204, None
            if path == f"{root}/credentials" and method == "GET":
                credentials = []
                if username in self.passwords_set:
                    credentials.append(
                        {"id": f"password-{current['id']}", "type": "password"}
                    )
                return 200, credentials
            mapping_path = f"{root}/role-mappings/realm"
            if path == mapping_path:
                return self._handle_user_roles(method, current["id"], body)
        return None

    def _handle_user_roles(
        self,
        method: str,
        user_uuid: str,
        body: Any,
    ) -> Response | None:
        """Read, add, or remove direct application realm roles.

        Args:
            method: HTTP method.
            user_uuid: Internal fake user UUID.
            body: Optional role representation list.

        Returns:
            Role-mapping response or ``None`` for an unsupported method.
        """

        assigned = self.user_roles[user_uuid]
        if method == "GET":
            return 200, [
                copy.deepcopy(self.realm_roles[name])
                for name in sorted(assigned)
            ]
        if not isinstance(body, list):
            raise AssertionError("User role mapping body must be a list.")
        names = {str(role["name"]) for role in body}
        if method == "POST":
            assigned.update(names)
            return 204, None
        if method == "DELETE":
            assigned.difference_update(names)
            return 204, None
        return None

    @staticmethod
    def _mapping(value: Any, action: str) -> dict[str, Any]:
        """Return a defensive mapping copy for one fake mutation.

        Args:
            value: Candidate request body.
            action: Secret-free operation label.

        Returns:
            Copied dictionary.

        Raises:
            AssertionError: If the body is not an object.
        """

        if not isinstance(value, dict):
            raise AssertionError(f"Fake {action} body must be an object.")
        return copy.deepcopy(value)


__all__ = ["StatefulApplicationAccess"]
