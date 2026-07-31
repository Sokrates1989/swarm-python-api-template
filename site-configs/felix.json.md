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
- Keycloak realm/client defaults `felix`, `felix-new-frontend`, and
  `felix-new-backend`, with protected legacy identity, selectable realm
  settings, application roles, and temporary test identities; and
- exact Docker secret identifiers and file mounts.

Felix recommends `storage.dataRoot: /swarm/prod/felix`. Pressing Enter at the
shared prompt therefore places `postgres_data`, `redis_data`, `backups`,
`logs`, and any other enabled service directory below that production clone.
Profiles with an absent or empty recommendation default to their actual
checkout instead. The common prompt also accepts another safe absolute path
when an operator intentionally wants a separate volume location.

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

The shared bootstrap reads callback templates, audience-mapper policy,
application-role and temporary test-user declarations, forbidden default
usernames, protected legacy identity, backend service-account roles, the fixed
Keycloak server trust anchor, and the confidential-client Docker secret target
from this JSON. Realm/display name, all six allowlisted realm booleans, managed
client IDs, test-user lifecycle, audience, and active service roots use these
profile values as defaults but may be changed in the guided bootstrap. Valid
selections are persisted to the ignored root `.env` and rebuild the generated
stack. It preserves all other realm settings, unrelated clients, and social
identity providers.
Every declared frontend callback is also admitted as a post-logout redirect,
including the native `felixkc:/callback`, while browser origins additionally
receive their Web wildcard.
The separate legacy `felixappnew` realm and declared legacy client/origin
remain protected. For Felix, the only declared backend grant is
`realm-management/manage-users`; undeclared broader grants in either the
service-account assignment or the backend client's dedicated scope, direct
realm roles other than Keycloak's generated default role, roles on undeclared
clients, and the unmanaged default `test` user block automatic apply.

The profile declares the production-facing application roles `user`, `admin`,
`manager`, and `service-provider`. The bootstrap creates or updates those roles
and adds them to the restricted frontend client's realm-role scope. These role
names are a forward-looking authorization contract; the current Felix API and
Flutter clients must still add feature-level enforcement as booking behavior
is implemented.

The initial profile default also enables four temporary identities:
`test-user`, `test-admin`, `test-manager`, and `test-service-provider`. Their
role assignments and public metadata are tracked, but their passwords are not.
For a missing user or password credential, the bootstrap prompts twice for a
hidden password after showing the authenticated plan and sends it only to
Keycloak. Every bootstrap
summary repeats: **Once you enter production mode, remember to delete those
users.** Turning the lifecycle switch off does not auto-delete identities; the
plan blocks until all four are explicitly removed from Keycloak. The managed
application roles remain after that cleanup.

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
