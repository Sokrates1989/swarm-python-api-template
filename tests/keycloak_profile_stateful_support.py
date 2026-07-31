"""
Module: keycloak_profile_stateful_support.py

Description:
    Provides a small stateful Keycloak Admin API fake for cross-module
    bootstrap tests. The fake models only the realm, client, mapper, role,
    public-metadata, and credential behavior owned by the executable profile,
    including Keycloak 26's derived service-client browser fields.

Dependencies:
    - Python standard library.
    - scripts/keycloak_profile_client.py.
"""

from __future__ import annotations

import copy
import urllib.parse
from typing import Any

from keycloak_profile_client import KeycloakIdentity
from tests.keycloak_profile_stateful_access_support import (
    StatefulApplicationAccess,
)


Response = tuple[int, Any]
RequestRecord = tuple[str, str, Any, dict[str, str] | None]


class StatefulKeycloakAdminClient:
    """Model the Keycloak state traversed by one fresh bootstrap."""

    def __init__(
        self,
        identity: KeycloakIdentity,
        client_secret: str,
    ) -> None:
        """Create an empty realm with one deterministic secret source.

        Args:
            identity: Profile-derived Keycloak identity.
            client_secret: Confidential value returned by the fake Keycloak
                client-secret endpoint.

        Returns:
            Nothing.
        """

        self.identity = identity
        self._client_secret = client_secret
        self.realm: dict[str, Any] | None = None
        self.clients: dict[str, dict[str, Any]] = {}
        self.mappers: dict[str, list[dict[str, Any]]] = {}
        self.assignment_roles: set[str] = set()
        self.scope_roles: set[str] = set()
        self.frontend_scope_roles: set[str] = set()
        self.application_access = StatefulApplicationAccess(identity)
        self.requests: list[RequestRecord] = []
        self.public_requests: list[str] = []
        self.events: list[str] = []

    @property
    def realm_root(self) -> str:
        """Return the escaped selected-realm Admin API root.

        Returns:
            Absolute fake Admin API realm path.
        """

        realm = urllib.parse.quote(self.identity.realm, safe="")
        return f"/admin/realms/{realm}"

    @property
    def clients_root(self) -> str:
        """Return the selected realm's client collection path.

        Returns:
            Absolute fake Admin API client collection path.
        """

        return f"{self.realm_root}/clients"

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
        query: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> Response:
        """Dispatch one Admin API request against mutable fake state.

        Args:
            method: HTTP method.
            path: Absolute Admin API path.
            body: Optional JSON-compatible request body.
            query: Optional query mapping.
            expected: Status codes accepted by production code.

        Returns:
            Fake HTTP status and a defensive copy of its response payload.

        Raises:
            AssertionError: If the route is unsupported or its status is not
                accepted by the caller.
        """

        recorded_body = self._recordable_body(path, body)
        self.requests.append((method, path, recorded_body, query))
        status, payload = self._dispatch(method, path, body, query)
        if status not in expected:
            raise AssertionError(
                f"Unexpected fake status {status} for {method} {path}; "
                f"expected {expected}."
            )
        return status, copy.deepcopy(payload)

    @staticmethod
    def _recordable_body(path: str, body: Any) -> Any:
        """Copy a request body without retaining runtime credential values.

        Args:
            path: Absolute Admin API request path.
            body: Optional request body.

        Returns:
            Defensive body copy, with password-reset values redacted.
        """

        copied = copy.deepcopy(body)
        if path.endswith("/reset-password") and isinstance(copied, dict):
            copied["value"] = "<redacted>"
        return copied

    def _dispatch(
        self,
        method: str,
        path: str,
        body: Any,
        query: dict[str, str] | None,
    ) -> Response:
        """Route one request to the focused fake resource handlers.

        Args:
            method: HTTP method.
            path: Absolute Admin API path.
            body: Optional request body.
            query: Optional query mapping.

        Returns:
            Handler-produced status and payload.

        Raises:
            AssertionError: If no modeled Keycloak resource matches.
        """

        handlers = (
            self._handle_realm,
            self._handle_client_collection,
            self._handle_mapper,
            self._handle_frontend_role_scope,
            self._handle_roles,
            self.application_access.handle,
            self._handle_secret,
            self._handle_client_representation,
            self._handle_users,
        )
        for handler in handlers:
            response = handler(method, path, body, query)
            if response is not None:
                return response
        raise AssertionError(f"Unsupported fake Keycloak request: {method} {path}")

    def _handle_realm(
        self,
        method: str,
        path: str,
        body: Any,
        query: dict[str, str] | None,
    ) -> Response | None:
        """Read, create, or update the selected realm.

        Args:
            method: HTTP method.
            path: Requested Admin API path.
            body: Optional realm representation.
            query: Optional query mapping, which must be absent.

        Returns:
            Realm response, or ``None`` when the route does not match.
        """

        if query is not None:
            return None
        if method == "GET" and path == self.realm_root:
            return (404, None) if self.realm is None else (200, self.realm)
        if method == "POST" and path == "/admin/realms":
            self.realm = self._require_mapping(body, "realm create")
            self._install_realm_management_client()
            return 201, None
        if method == "PUT" and path == self.realm_root:
            self.realm = self._require_mapping(body, "realm update")
            return 204, None
        return None

    def _install_realm_management_client(self) -> None:
        """Install the built-in role-owning client after realm creation.

        Returns:
            Nothing.
        """

        self.clients["realm-management"] = {
            "id": "realm-management-uuid",
            "clientId": "realm-management",
        }

    def _handle_client_collection(
        self,
        method: str,
        path: str,
        body: Any,
        query: dict[str, str] | None,
    ) -> Response | None:
        """Resolve or create clients in the selected realm.

        Args:
            method: HTTP method.
            path: Requested Admin API path.
            body: Optional client representation.
            query: Optional exact client-ID query.

        Returns:
            Client collection response, or ``None`` for another route.
        """

        if path != self.clients_root:
            return None
        if method == "GET" and query is not None:
            client_id = query.get("clientId")
            current = self.clients.get(str(client_id))
            return 200, [] if current is None else [current]
        if method == "POST" and query is None:
            payload = self._require_mapping(body, "client create")
            self._apply_keycloak_client_defaults(payload)
            client_id = str(payload["clientId"])
            payload["id"] = self._client_uuid(client_id)
            self.clients[client_id] = payload
            return 201, None
        return None

    def _apply_keycloak_client_defaults(
        self,
        payload: dict[str, Any],
    ) -> None:
        """Model Keycloak 26 browser fields derived from a service root URL.

        Args:
            payload: Mutable client representation received by the fake.

        Returns:
            Nothing. The backend representation gains the same redirect and
            origin defaults observed in Keycloak 26 read-back responses.
        """

        if payload.get("clientId") != self.identity.backend_client_id:
            return
        root_url = str(payload.get("rootUrl", "")).rstrip("/")
        if not root_url:
            return
        payload.setdefault("redirectUris", [f"{root_url}/*"])
        payload.setdefault("webOrigins", [root_url])

    def _client_uuid(self, client_id: str) -> str:
        """Return a deterministic UUID for one profile-owned client.

        Args:
            client_id: Public Keycloak client identifier.

        Returns:
            Stable fake internal client UUID.
        """

        if client_id == self.identity.frontend_client_id:
            return "frontend-uuid"
        if client_id == self.identity.backend_client_id:
            return "backend-uuid"
        return f"{client_id}-uuid"

    def _handle_client_representation(
        self,
        method: str,
        path: str,
        body: Any,
        query: dict[str, str] | None,
    ) -> Response | None:
        """Read or update one exact client representation.

        Args:
            method: HTTP method.
            path: Requested Admin API path.
            body: Optional replacement representation.
            query: Optional query mapping, which must be absent.

        Returns:
            Client response, or ``None`` for another route.
        """

        if query is not None:
            return None
        for client_id, current in self.clients.items():
            target = f"{self.clients_root}/{current['id']}"
            if path != target:
                continue
            if method == "GET":
                return 200, current
            if method == "PUT":
                replacement = self._require_mapping(
                    body,
                    "client update",
                )
                self._apply_keycloak_client_defaults(replacement)
                self.clients[client_id] = replacement
                return 204, None
        return None

    def _handle_mapper(
        self,
        method: str,
        path: str,
        body: Any,
        query: dict[str, str] | None,
    ) -> Response | None:
        """Read, create, or update the frontend audience mapper.

        Args:
            method: HTTP method.
            path: Requested Admin API path.
            body: Optional mapper representation.
            query: Optional query mapping, which must be absent.

        Returns:
            Mapper response, or ``None`` for another route.
        """

        frontend = self.clients.get(self.identity.frontend_client_id)
        if query is not None or frontend is None:
            return None
        root = (
            f"{self.clients_root}/{frontend['id']}/"
            "protocol-mappers/models"
        )
        if path == root and method == "GET":
            return 200, self.mappers.get(str(frontend["id"]), [])
        if path == root and method == "POST":
            mapper = self._require_mapping(body, "mapper create")
            mapper["id"] = "audience-mapper-uuid"
            self.mappers[str(frontend["id"])] = [mapper]
            return 201, None
        if path == f"{root}/audience-mapper-uuid" and method == "PUT":
            mapper = self._require_mapping(body, "mapper update")
            self.mappers[str(frontend["id"])] = [mapper]
            return 204, None
        return None

    def _handle_roles(
        self,
        method: str,
        path: str,
        body: Any,
        query: dict[str, str] | None,
    ) -> Response | None:
        """Serve service-account assignment and dedicated-scope endpoints.

        Args:
            method: HTTP method.
            path: Requested Admin API path.
            body: Optional role-representation list.
            query: Optional query mapping, which must be absent.

        Returns:
            Role response, or ``None`` for another route.
        """

        backend = self.clients.get(self.identity.backend_client_id)
        if query is not None or backend is None:
            return None
        paths = self._role_paths(str(backend["id"]))
        if path == paths["account"] and method == "GET":
            return 200, {"id": "service-account-user"}
        if path == paths["assignmentInventory"] and method == "GET":
            return 200, self._mapping_inventory(self.assignment_roles, True)
        if path == paths["scopeInventory"] and method == "GET":
            return 200, self._mapping_inventory(self.scope_roles, False)
        if path == paths["effectiveScope"] and method == "GET":
            return 200, [
                {"id": f"{name}-role-uuid", "name": name}
                for name in sorted(self.scope_roles)
            ]
        if path == paths["role"] and method == "GET":
            return 200, self._role_representation()
        if path == paths["assignment"]:
            return self._handle_direct_mapping(method, body, self.assignment_roles)
        if path == paths["scope"]:
            return self._handle_direct_mapping(method, body, self.scope_roles)
        return None

    def _handle_frontend_role_scope(
        self,
        method: str,
        path: str,
        body: Any,
        query: dict[str, str] | None,
    ) -> Response | None:
        """Read or add application realm roles in the frontend client scope.

        Args:
            method: HTTP method.
            path: Requested Admin API path.
            body: Optional realm-role representation list.
            query: Optional query mapping, which must be absent.

        Returns:
            Frontend role-scope response, or ``None`` for another route.
        """

        frontend = self.clients.get(self.identity.frontend_client_id)
        if frontend is None or query is not None:
            return None
        target = (
            f"{self.clients_root}/{frontend['id']}/scope-mappings/realm"
        )
        if path != target:
            return None
        if method == "GET":
            return 200, [
                self.application_access.realm_roles[name]
                for name in sorted(self.frontend_scope_roles)
            ]
        if method == "POST":
            if not isinstance(body, list):
                raise AssertionError("Frontend role scope body must be a list.")
            self.frontend_scope_roles.update(
                str(role["name"]) for role in body
            )
            return 204, None
        return None

    def _role_paths(self, backend_uuid: str) -> dict[str, str]:
        """Build every role endpoint used by production reconciliation.

        Args:
            backend_uuid: Internal confidential-client UUID.

        Returns:
            Named exact Admin API paths.
        """

        role_client = "realm-management-uuid"
        return {
            "account": (
                f"{self.clients_root}/{backend_uuid}/service-account-user"
            ),
            "assignmentInventory": (
                f"{self.realm_root}/users/service-account-user/role-mappings"
            ),
            "scopeInventory": (
                f"{self.clients_root}/{backend_uuid}/scope-mappings"
            ),
            "assignment": (
                f"{self.realm_root}/users/service-account-user/"
                f"role-mappings/clients/{role_client}"
            ),
            "scope": (
                f"{self.clients_root}/{backend_uuid}/"
                f"scope-mappings/clients/{role_client}"
            ),
            "effectiveScope": (
                f"{self.clients_root}/{backend_uuid}/evaluate-scopes/"
                f"scope-mappings/{role_client}/granted"
            ),
            "role": (
                f"{self.clients_root}/{role_client}/roles/manage-users"
            ),
        }

    def _mapping_inventory(
        self,
        roles: set[str],
        include_default_realm_role: bool,
    ) -> dict[str, Any]:
        """Build one Keycloak complete role-mapping representation.

        Args:
            roles: Direct realm-management roles.
            include_default_realm_role: Include the service account's default
                realm role when true.

        Returns:
            Keycloak-compatible mapping inventory.
        """

        realm_mappings = []
        if include_default_realm_role:
            realm_mappings.append(
                {"name": f"default-roles-{self.identity.realm}"}
            )
        client_mappings: dict[str, Any] = {}
        if roles:
            client_mappings["realm-management"] = {
                "client": "realm-management",
                "mappings": [
                    {"id": f"{name}-role-uuid", "name": name}
                    for name in sorted(roles)
                ],
            }
        return {
            "realmMappings": realm_mappings,
            "clientMappings": client_mappings,
        }

    def _handle_direct_mapping(
        self,
        method: str,
        body: Any,
        target: set[str],
    ) -> Response | None:
        """Read or append one direct client-role mapping.

        Args:
            method: HTTP method.
            body: Optional role-representation list.
            target: Mutable role-name set owned by the mapping.

        Returns:
            Direct mapping response, or ``None`` for an unsupported method.
        """

        if method == "GET":
            return 200, [
                {"id": f"{name}-role-uuid", "name": name}
                for name in sorted(target)
            ]
        if method == "POST":
            if not isinstance(body, list):
                raise AssertionError("Role mapping body must be a list.")
            target.update(str(role["name"]) for role in body)
            return 204, None
        return None

    def _role_representation(self) -> dict[str, str]:
        """Return the declared manage-users role representation.

        Returns:
            Fake role accepted by assignment and scope endpoints.
        """

        return {
            "id": "manage-users-role-uuid",
            "name": "manage-users",
        }

    def _handle_secret(
        self,
        method: str,
        path: str,
        body: Any,
        query: dict[str, str] | None,
    ) -> Response | None:
        """Return the backend credential from Keycloak's secret endpoint.

        Args:
            method: HTTP method.
            path: Requested Admin API path.
            body: Optional body, which must be absent.
            query: Optional query mapping, which must be absent.

        Returns:
            Secret response, or ``None`` for another route.
        """

        backend = self.clients.get(self.identity.backend_client_id)
        if backend is None or body is not None or query is not None:
            return None
        target = f"{self.clients_root}/{backend['id']}/client-secret"
        if method == "GET" and path == target:
            self.events.append("secret-read")
            return 200, {"value": self._client_secret}
        return None

    def _handle_users(
        self,
        method: str,
        path: str,
        body: Any,
        query: dict[str, str] | None,
    ) -> Response | None:
        """Return an empty exact-user search for forbidden-user checks.

        Args:
            method: HTTP method.
            path: Requested Admin API path.
            body: Optional body, which must be absent.
            query: Exact username lookup.

        Returns:
            Empty user response, or ``None`` for another route.
        """

        if (
            method == "GET"
            and path == f"{self.realm_root}/users"
            and body is None
            and query is not None
            and query.get("exact") == "true"
        ):
            return 200, []
        return None

    def public_json(self, url: str) -> dict[str, Any]:
        """Return public discovery or JWKS evidence for the created realm.

        Args:
            url: Exact public metadata URL.

        Returns:
            Discovery or signing-key document.

        Raises:
            AssertionError: If metadata is requested before realm creation or
                from an undeclared URL.
        """

        if self.realm is None:
            raise AssertionError("Public metadata requested before realm creation.")
        self.public_requests.append(url)
        discovery = (
            f"{self.identity.issuer_url}/"
            ".well-known/openid-configuration"
        )
        if url == discovery:
            return {"issuer": self.identity.issuer_url}
        if url == self.identity.jwks_url:
            return {"keys": [{"kid": "signing-key-1"}]}
        raise AssertionError(f"Unsupported public Keycloak URL: {url}")

    def prove_client_credentials(
        self,
        client_id: str,
        client_secret: str,
    ) -> None:
        """Prove the real returned secret and effective backend authority.

        Args:
            client_id: Confidential backend client identifier.
            client_secret: Keycloak-returned credential held by production
                orchestration.

        Returns:
            Nothing after credential and effective-role checks succeed.

        Raises:
            AssertionError: If the wrong secret is used or the backend token
                would lack ``manage-users`` authority.
        """

        if client_id != self.identity.backend_client_id:
            raise AssertionError("Credential proof used the wrong client.")
        if client_secret != self._client_secret:
            raise AssertionError("Credential proof did not use Keycloak's secret.")
        backend = self.clients.get(client_id)
        if backend is None or backend.get("serviceAccountsEnabled") is not True:
            raise AssertionError("Backend service account is not enabled.")
        if "manage-users" not in self.assignment_roles:
            raise AssertionError("Service account lacks manage-users.")
        if "manage-users" not in self.scope_roles:
            raise AssertionError("Backend scope omits manage-users.")
        self.events.append("proof")

    @staticmethod
    def _require_mapping(value: Any, action: str) -> dict[str, Any]:
        """Copy one required JSON object.

        Args:
            value: Candidate request body.
            action: Secret-free operation label.

        Returns:
            Defensive mapping copy.

        Raises:
            AssertionError: If the request body is not an object.
        """

        if not isinstance(value, dict):
            raise AssertionError(f"Fake {action} body must be an object.")
        return copy.deepcopy(value)


__all__ = ["StatefulKeycloakAdminClient"]
