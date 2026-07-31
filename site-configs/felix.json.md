# Felix site profile

## Purpose and ownership

`felix.json` is a secret-free schema-5 site profile. It supplies data to the
same executable setup and deployment path available to every other app. There
is no Felix setup wizard, renderer, Keycloak adapter, secret menu, deployment
state machine, health path, log path, or rollback implementation.

Felix differs only through profile data:

- stack `felix`;
- WebApp host `felix-app.fe-wi.com`;
- API host `api.felix-app.fe-wi.com`;
- optional WebApp service enabled with image
  `sokrates1989/flutter-felix-web`;
- backend image `sokrates1989/python-api-felix`;
- Redis and local/external PostgreSQL;
- optional pgAdmin;
- isolated Keycloak realm `felix-new`, public client `felix-new-frontend`, and
  confidential backend client/audience `felix-new-backend`; and
- exact Docker secret identifiers and file mounts.

The legacy host `felix.app.fe-wi.com` is deliberately absent from executable
routing and remains outside this stack.

## WebApp service

`services.web: true` instructs the common renderer to add the WebApp to the
same stack. The `web` object owns its image, semantic version, replicas, and
memory. `routing.web*` owns its public host, container health endpoint, and
optional direct published port. Routing also declares the default Traefik
overlay network, independent provider constraint label, certificate resolver,
and direct pgAdmin port; the shared wizard collects the actual operator
choice.

Any other app can add a WebApp in exactly the same way. Disabling
`services.web` and removing the associated WebApp fields produces an API-only
stack without modifying production code.

## Keycloak and secrets

The running Keycloak platform remains the existing `swarm-keycloak`
deployment. The app menu uses the public Admin API of that existing server; it
never deploys another Keycloak instance and never depends on the local
development `keycloak` repository.

The shared bootstrap reads realm-owned settings, clients, callbacks, origins,
audience mapper, forbidden default usernames, protected legacy identity,
backend service-account client roles, and the confidential-client Docker
secret target from this JSON. It reconciles only the allowlisted
`realmSettings` fields and preserves all other realm settings and social
identity providers. Stack identity is independent from authentication
identity: the stack is `felix`, while the candidate realm and clients retain
the isolated `felix-new` names required by the published application images.
Every declared frontend callback is also admitted as a post-logout redirect,
including the native `felixkc:/callback`, while browser origins additionally
receive their Web wildcard.
The legacy `felix` realm remains protected. For Felix, the only declared
backend grant is `realm-management/manage-users`; undeclared broader grants
in either the service-account assignment or the backend client's dedicated
scope, direct realm roles other than Keycloak's generated default role,
roles on undeclared clients, and the default `test` user block automatic
apply.

Administrator password and backend client secret are never printed, written
to `.env`, put in command arguments, or saved to a repository file. The
bootstrap first shows a sanitized live-state plan. After apply, it reads all
owned state back and verifies the public issuer and JWKS. When the Docker
secret is missing, the real current Keycloak credential is fetched, proven
through the client-credentials token endpoint and a read-only realm-user
Admin API request, and streamed unchanged from memory to
`docker secret create`.

An existing Docker secret cannot be read back by Docker Swarm, so it is
reported as `present-unverified` rather than falsely described as synchronized.
Explicit rotation first regenerates and proves the Keycloak credential and
then replaces the profile-declared Docker secret while the app stack is
stopped. Because Docker secrets are immutable, replacement first creates a
temporary recovery secret containing the same proven value. It removes that
recovery object only after the fixed-name target is recreated; failures report
the recovery object name without exposing its value.

Required and optional secret names are identifiers only. Runtime values are
mounted through their declared `*_FILE` fields.

## Images, safety, and validation

API and WebApp release tags are semantic versions. Redis, PostgreSQL, and
pgAdmin images are digest pinned. Direct secret fields, mutable release aliases
such as `latest`, debug logging, wildcard origins, and unresolved placeholders
are rejected.

Use `./quick-start.sh`, select **Felix Backend and WebApp**, and follow the
shared setup flow. It writes root `.env` and renders one
`swarm-stack.yml`. It does not deploy until the normal deployment menu action
is selected.

Direct validation:

```bash
python3 scripts/site_profile.py --root . validate-stack --compose-check
```
