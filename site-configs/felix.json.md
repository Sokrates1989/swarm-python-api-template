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

The shared bootstrap reads realm, clients, callbacks, origins, audience,
protected legacy identity, backend service-account client roles, and the
confidential-client Docker secret target from this JSON. It preserves
unrelated realm settings and social identity providers. Stack identity is
independent from authentication identity: the stack is `felix`, while the
candidate realm and clients retain the isolated `felix-new` names required by
the published application images. The legacy `felix` realm remains protected.
For Felix, the only declared backend grant is
`realm-management/manage-users`; undeclared broader grants fail closed.

Administrator password and backend client secret are never printed, written
to `.env`, put in command arguments, or saved to a repository file. Existing
Docker secret state is kept without retrieving client-secret material.
Explicit rotation first regenerates the Keycloak credential and then replaces
the profile-declared Docker secret while the app stack is stopped.

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
