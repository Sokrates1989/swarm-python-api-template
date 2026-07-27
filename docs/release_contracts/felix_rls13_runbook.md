# Felix RLS-13 candidate deployment runbook

## Scope

This runbook deploys only the isolated `felix-new` candidate stack at
`api.felix-app.fe-wi.com`. It never changes the legacy host
`felix.app.fe-wi.com`, its running stack, either protected legacy Keycloak
realm (`felix` or `felixappnew`), or forwarding/cutover state.

The authoritative operator entry point is `./quick-start.sh`. For the exact
Felix candidate profile, its normal deploy, status, and log actions route to
the strict state machine in `scripts/felix_deploy.py`; generic image-update,
scale, and stack-render actions are blocked.

## Keycloak checkout ownership

The two Keycloak repositories have different responsibilities and must remain
separate:

- `/swarm/administration/keycloak` is the existing running Keycloak deployment
  checkout from `https://github.com/Sokrates1989/swarm-keycloak.git`. Do not
  replace, relocate, or modify this checkout for the Felix candidate.
- `/swarm/keycloak` is a separate, clean checkout of
  `https://github.com/Sokrates1989/keycloak.git`, pinned exactly at
  `5096ea7820874bbb66dbc6162043c4348c8c95e5`. It is the canonical
  reconciliation tool used by the Felix quick-start menu.

The canonical tool talks to the already-running Keycloak server through its
administration API. It updates only the approved `felix-new` realm fields; it
does not deploy a second Keycloak stack or replace the deployment repository.

## Image publication boundary

The API repository owns image planning, local proof, and publication. Start
its `quick-start.ps1` or `quick-start.sh`, verify that `felix` is the selected
backend app, and use these menu actions in order:

1. **Validate API Docker image release plan**.
2. **Build API Docker image locally (no push)**.
3. **Build & Push API Docker Image (current or bump + version + latest)**.

The third action is the only supported image publication path. Do not run raw
Docker build/tag/push commands, invoke the underlying Python publisher
directly, or use a CI/CD pipeline. The menu keeps the current version or
increments it, pushes or replaces the selected version tag, records its
registry digest, and updates `latest` as a convenience tag. It leaves Git
source local for the operator to push separately and never deploys.

This Swarm repository never builds or pushes the API image. It consumes only
the exact semantic version selected by `site-configs/felix.json`, resolves
that tag to an immutable digest during strict preflight, and rejects `latest`.

At the current RLS-13 checkpoint, the API repository and this Swarm profile
both contain `0.1.1`. Choose **Keep current** so the menu publishes exactly
`0.1.1` without a new version-bump commit. The menu may intentionally replace
an existing `0.1.1` tag; strict Swarm preflight resolves the resulting digest
and deployment remains bound to that digest. Do not run Swarm preflight until
publication succeeds. The same exact version-alignment rule applies to every
later release.

## One-time prerequisites

Keep `/swarm/administration/keycloak` on the deployed `swarm-keycloak`
repository. Prepare the separate `/swarm/keycloak` tooling checkout from
`keycloak.git` with a clean worktree exactly at
`5096ea7820874bbb66dbc6162043c4348c8c95e5` before opening the Felix Keycloak
menu.

1. Publish the Felix API through the API quick-start menu described above.
   The matching semantic tag in `site-configs/felix.json` must exist in the
   registry, resolve to one immutable digest, target `linux/amd64`, and contain
   the exact Felix OCI identity labels.
2. Copy `prod.env.example` to ignored `prod.env`, then set both `.invalid`
   values to `api.felix-app.fe-wi.com`. Keep this file public-only.
3. Make `api.felix-app.fe-wi.com` resolve to the existing proxy and ensure a
   publicly trusted TLS certificate is available.
4. Use **Felix candidate Keycloak** in the quick-start menu to run check,
   plan, approved apply, verify, and protected-legacy verification.
5. Use that menu’s secret bridge to create
   `FELIX_NEW_KEYCLOAK_ADMIN_CLIENT_SECRET` directly from canonical Keycloak.
6. Create `FELIX_NEW_DB_PASSWORD` with the repository secret manager or an
   equivalent stdin-only Docker secret flow. Never place either secret in
   `.env`, `prod.env`, shell arguments, logs, or a tracked file.
   The strict **Manage Docker secrets** menu offers this database-secret action
   but deliberately routes the Keycloak client secret only through the
   canonical bridge.
7. Ensure the external Swarm overlay network `traefik-public` exists.

## First candidate deployment

Open **Felix strict deploy / health / rollback** and run:

1. **Prepare exact candidate data directories.**
2. **Run strict preflight.**
3. **Backup, deploy candidate, and require strict health.**
4. **Run strict health and legacy continuity checks.**

Preflight fails closed unless the public profile, registry digest/platform and
OCI labels, active Swarm manager, Docker secrets, overlay network, candidate
directories, Compose render, DNS/TLS, candidate issuer/JWKS, legacy issuer,
and legacy web application all match.

The first deployment retains a mode-0600 declaration proving the PostgreSQL
directory was empty. Later deployments retain and structurally verify a
custom-format `pg_dump` before changing the service.

The API update uses `start-first` order with Docker
`failure_action: rollback`. The command additionally requires converged
replicas, the exact API digest, HTTPS health, production/Felix/PostgreSQL/SQL
runtime identity, successful startup and migrations, Keycloak configuration
and audience enforcement, an anonymous protected-route rejection, exact
version, issuer/JWKS, and secret-safe recent logs.

## Rollback proof

After the first healthy deployment, choose **Run bad-candidate automatic
rollback drill** once. The drill:

1. requires a healthy digest-bound candidate;
2. inserts one isolated random marker into
   `release_orchestration.markers`;
3. attempts an API update to the already pinned Redis image;
4. requires a newer Docker service version in state
   `rollback_completed` at the exact prior API digest;
5. repeats strict health and legacy-continuity checks; and
6. verifies that the database marker survived.

The drill never publishes an intentionally bad image and never touches a
legacy service. An explicit candidate API rollback remains available as menu
option 8 for a later real release incident.

## Evidence and failure behavior

Sanitized mode-0600 JSON receipts are written under ignored
`build/release-evidence/swarm/felix/`. Database evidence lives below
`/swarm/volumes/felix-new/backups/release/`.

If deployment fails after it starts, the state machine restores the captured
candidate API service image. A failed first candidate deployment removes only
the `felix-new` stack. If rollback itself cannot be proved, the command exits
nonzero and retains a `rollback-failed` receipt; it never reports success.

Do not configure forwarding from `felix.app.fe-wi.com` during RLS-13. That is
an explicit later cutover decision.
