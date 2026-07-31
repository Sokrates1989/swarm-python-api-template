# Felix candidate deployment runbook

## Scope

This runbook creates the `felix` stack for:

- WebApp: `https://felix-app.fe-wi.com`;
- API: `https://api.felix-app.fe-wi.com`;
- Redis;
- local or external PostgreSQL; and
- optional pgAdmin.

It does not modify `https://felix.app.fe-wi.com`, a legacy stack, a legacy
realm, or later forwarding/cutover state.

Felix uses the repository's default site-config flow. There are no Felix-only
setup, Keycloak, secret, deployment, health, log, or rollback actions.
`site-configs/felix.json` adds the WebApp by declaring
`services.web: true`; any app can do the same.

## Publish images from their owning quick-start menus

Do not build or push application images from this Swarm checkout, raw Docker
commands, or a CI/CD pipeline.

For the backend:

1. open the `python-api-template` quick-start menu;
2. select backend app `felix`;
3. validate the Docker image release plan;
4. build locally; and
5. use **Build & Push API Docker Image** with version `0.1.1` or the later
   version deliberately selected for deployment.

For the WebApp:

1. open the `flutter_app_template` quick-start menu;
2. select app `felix`;
3. open **Build & Deploy Selected App > Web**;
4. build the selected-app Web image; and
5. publish `sokrates1989/flutter-felix-web` with version `1.0.5` or the later
   version deliberately selected for deployment.

Both publication menus may update `latest` as a convenience tag. The Swarm
profile never deploys `latest`; it requires semantic versions. Normal stack
deployment uses `docker stack deploy --resolve-image always`, so Docker
records the registry-resolved image identity in each service specification.

## Existing production Keycloak

Production Keycloak is already running from:

```text
/swarm/administration/keycloak
https://github.com/Sokrates1989/swarm-keycloak.git
```

Do not clone `D:\Development\Code\keycloak` or its remote on a production
server. That repository is for local development. Do not create a second
Keycloak stack.

The Felix deployment menu talks to the existing server's Admin API. The site
profile provides realm/client defaults, callback and policy templates,
protected identity, and the target Docker-secret name. Validated active
realm/client/root choices live in the ignored root `.env`. The stack name
remains `felix`; stack and authentication identity are independent. Re-running
the action is idempotent: it preserves unrelated realm settings and social
identity providers while reconciling the selected clients. The separate
legacy realm `felixappnew`, its declared legacy client, and its origin remain
protected and are never candidate bootstrap targets.

The administrator password is entered without terminal echo. The confidential
backend secret is not printed or written to `.env`; when its Docker secret is
missing, it is transferred directly from process memory to Docker standard
input.

## Configure the server clone

From the Swarm deployment clone, run:

```bash
./quick-start.sh
```

If no root `.env` exists:

1. choose **Run setup wizard**;
2. select **Felix Backend and WebApp**;
3. confirm or change the stack name plus API and WebApp domains;
4. choose local or external PostgreSQL through the numbered database menu;
5. choose Traefik or direct published ports and the correct TLS ownership;
6. choose the real Traefik overlay network from the discovered numbered list;
7. confirm backend and WebApp image repositories, semantic versions,
   replicas, memory, and optional pgAdmin; at **Host data root**, press Enter to
   accept the checkout default (`/swarm/prod/felix`) unless an intentional
   separate absolute host path is required; and
8. let the wizard write root `.env` and Compose-validate
   `swarm-stack.yml`.

Do not create `prod.env`. Root `.env` is the normal ignored production
configuration for this clone. It contains public configuration only.

For Traefik, ensure the declared `traefik-public` overlay network exists and
both candidate DNS names reach the proxy. With upstream SSL termination,
select proxy TLS mode. With Traefik certificate ownership, select the
Let's Encrypt mode.

## Bootstrap/update the realm

Choose **Bootstrap / update Keycloak realm** from the same quick-start menu.
Review the server, realm, display name, frontend/backend client IDs, frontend
and backend roots, audience, all six managed realm settings, and the temporary
test-user lifecycle through their Enter-default prompts. Entered values replace
the defaults, are validated against protected legacy identity, persist to root
`.env`, and rebuild `swarm-stack.yml` before authentication. If the prior
audience matched the prior backend client ID, entering a different backend ID
also becomes the proposed audience; accept it or enter a deliberately distinct
resource-server audience.
The Keycloak server is shown as a fixed tracked credential trust anchor.
WebApp/mobile artifacts must be built with the selected realm and client IDs.
Optionally enable secret-safe request tracing, then enter the existing
Keycloak admin username and its password at the immediately following hidden
Python prompt.

The profile declares the application roles `user`, `admin`, `manager`, and
`service-provider`, plus four temporary role-specific users. When an enabled
user or its password credential is missing, enter and confirm its password at
the hidden prompts shown after the authenticated live-state plan. Passwords are
sent only to Keycloak and never enter JSON, `.env`, logs, plans, or summaries. Every run
with temporary users enabled warns: **Once you enter production mode, remember
to delete those users.** To enter production mode, disable the test-user
lifecycle, explicitly delete the four declared users from Keycloak, and rerun
the bootstrap until its cleanup blockers are gone. Application roles remain.

If an existing Docker client secret belongs to a previously selected realm or
backend client, stop the Felix stack and use the explicit Keycloak secret
rotation action after saving the new identity. The bootstrap deliberately does
not silently reinterpret an opaque existing Swarm secret.

Tracing contains only HTTP methods, Admin API paths, query-key names, and
status codes. Bodies, headers, query values, tokens, passwords, and client
secrets are never logged. Any strict read-back failure names its remaining
profile-owned fields.

With the profile defaults, the shared action ensures (entered deployment
values replace the corresponding realm/client/root names below):

- existing realm `felix` is reconciled without replacing unrelated clients or
  social identity providers;
- public PKCE client `felix-new-frontend` has the exact Web and mobile callback
  allowlist;
- confidential service client `felix-new-backend` exists;
- frontend access tokens receive audience `felix-new-backend`; and
- application realm roles `user`, `admin`, `manager`, and `service-provider`
  exist and are included in the restricted frontend client role scope;
- when enabled, temporary users `test-user`, `test-admin`, `test-manager`, and
  `test-service-provider` exist with their exact declared application roles;
- the backend service account receives only the declared
  `realm-management/manage-users` client role needed for identity deletion;
- broader undeclared role grants fail closed for manual review; and
- missing Docker secret
  `FELIX_KEYCLOAK_ADMIN_CLIENT_SECRET` is created.

If that Docker secret already exists, it is kept without retrieving client
secret material. Use the separate explicit rotation action only when
intentional and only after stopping the selected stack. Rotation calls
Keycloak's client-secret regeneration endpoint first, then replaces the exact
profile-declared Docker secret from process memory; it is not merely a
re-synchronization of the old credential.

Social providers remain managed on the existing Keycloak deployment. Their
configuration is not replaced by app bootstrap.

## Prepare secrets and storage

Choose **Manage Docker secrets**. The exact list is read from the profile.

For the current Felix profile:

- create `FELIX_DB_PASSWORD`;
- verify the Keycloak bootstrap created
  `FELIX_KEYCLOAK_ADMIN_CLIENT_SECRET`; and
- create `FELIX_PGADMIN_PASSWORD` only if pgAdmin is enabled.

Optional AI chat and Web Push secrets are shown separately. They become
required only when their corresponding site-config capability is enabled.

Create the data directories offered by the setup wizard. With the current
recommended default they are ignored subdirectories of `/swarm/prod/felix`;
an explicitly selected external data root is also supported. Secret values
must never be placed in site config, root `.env`, command arguments, logs, or
tracked files.

## First deployment

From the common deployment menu:

1. choose **Rebuild swarm stack** and require a successful Compose check;
2. choose **Deploy to Docker Swarm** and press Enter to confirm;
3. choose **Check deployment status** until all declared services converge;
4. verify WebApp health at `https://felix-app.fe-wi.com/health`;
5. verify API health at `https://api.felix-app.fe-wi.com/health`; and
6. use **View service logs** to inspect WebApp, API, Redis, PostgreSQL, and
   optional pgAdmin without relying on app-specific service lists.

API and WebApp services use start-first updates, monitored health checks, and
`failure_action: rollback`. A normal redeploy updates the existing stack in
place; it does not remove the stack first.

## Rollback proof

After one healthy deployment, test the generic rollback flow during a planned
maintenance window:

1. publish and deploy a second known-good semantic version of at least one
   service so Docker retains a previous specification;
2. confirm the stack is healthy;
3. choose **Roll back retained service specifications**;
4. press Enter to start the rollback;
5. watch the configured `felix` stack until the service converges; and
6. rerun the common status and public health checks.

Docker reports a warning for a service that has no retained previous
specification. The rollback action is shared by every profile and does not
target a hard-coded service list.

For an actual failed rolling update, the service's configured
`failure_action: rollback` is the first protection. The explicit menu action is
the operator-controlled fallback.

This first runbook proves the shared operator path. `RLS-13` remains open until
the shared status action fails nonzero on injected WebApp/API health faults,
the database backup/data-continuity checks pass, and the previous immutable
image identities are recorded after rollback.

## Cutover remains later

Do not forward `felix.app.fe-wi.com` during this deployment. Legacy forwarding
requires a separate, explicit and reversible cutover decision after candidate
Web, Android, backend, authentication, and rollback evidence is accepted.
