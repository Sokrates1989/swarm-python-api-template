# Setup modules

These modules implement the reusable setup and operations menu. The
authoritative production workflow is Bash on the Linux Swarm host. Use WSL
when this flow needs to be inspected from Windows; archived native PowerShell
deployment scripts are not maintained.

## Architectural invariant

Production modules must not branch on an application ID, profile filename,
stack name, domain, realm, client ID, image name, or secret prefix. Every app
uses the same menu. Differences are selected from `site-configs/<profile>.json`
through schema and capability fields.

In particular:

- `renderer.type` selects the persistence/rendering strategy only after the
  shared dialogue;
- `services` selects API, WebApp, Redis, and database services;
- `database` selects engine, local/external mode, images, and optional admin
  UI;
- `routing` and `exposure` select the Traefik overlay network, provider
  constraint label, resolver, or direct ports;
- `auth.provider` controls authentication actions;
- `auth` contains Keycloak identity, selectable realm defaults, application
  roles, secret-free temporary test users, protected legacy values, and exact
  service-account client roles;
- `release` optionally enrolls application artifacts in independently
  advancing component minimums for their next build/publication; those
  minimums are not deployment freshness and this site profile is their single
  authority;
- `secrets`, `optionalSecrets`, and `secretMounts` control exact Docker
  secrets, including profile-discovered paired VAPID setup; and
- `capabilities` contributes optional public environment and secret mounts.

Felix therefore uses no special module. Its WebApp is simply
`services.web: true`.

## Core modules

### `site_helpers.sh`

Discovers profiles, loads selected JSON metadata, and reloads public root
`.env` values for the menu.

### `deployment-profile-prompts.sh`

Owns the numbered choice and validated free-text primitives. Enum and boolean
profile values never fall back to renderer-specific raw text prompts. Values
validated as public domains automatically show the shared Wiki subdomain-
creation link, so new profile capabilities inherit the same operator guidance.

### `deployment-field-help.sh`

Owns the shared accepted-value explanations used by both guided prompts and
the generated public `.env` editor, keeping instructions DRY across setup
modes.

### `deployment-environment-format.sh`

Formats freshly generated public environments into canonical, visually
separated blocks aligned with site-profile responsibilities. It consolidates
repeated accepted-value notes per block, preserves assignment values exactly,
rejects duplicate or unsupported generated lines, and replaces the file with
mode `0600` without evaluating dotenv content.

### `deployment-memory-policy.sh`

Owns the shared optional-memory contract for both renderer families. It
normalizes Enter, `unlimited`, and `0` to the unconstrained sentinel, validates
explicit Docker byte quantities, prints the unit guidance before each memory
prompt, and removes marked Compose limit blocks when no constraint is selected.

### `deployment-profile-inputs.sh`

Runs the only deployment dialogue. It normalizes profile defaults and existing
`.env` values, then collects applicable stack, domain, database, proxy/TLS,
Traefik network, service image/tag/replica/memory/port, storage, admin-service,
internal-network, and redirector values. The host storage prompt uses an
optional profile recommendation, falls back to the checkout root when it is
absent or empty, and preserves an existing explicit choice during
reconfiguration.

`deployment-profile-routing.sh` and `deployment-profile-services.sh` contain
the larger capability sections while remaining part of this one dialogue.

### Persistence and renderer adapters

`legacy-profile-environment.sh` writes the schema-3 compatibility environment.
`executable-profile-wizard.sh` is now a prompt-free schema-5 persistence and
render adapter. Both consume the same normalized answers. The latter calls
`scripts/site_profile.py` for strict validation and deterministic rendering.

### `deployment-setup-actions.sh`

Owns one dynamically numbered final-action menu. Docker secrets and Keycloak
actions appear only when the profile declares those capabilities. Every direct
or full deployment first invokes the common data-directory preparation step;
the operation is cached only within that one menu process after it succeeds.
The deployment boundary accepts an internal `confirmed` mode only for parent
workflows that have already shown and confirmed the exact mutation plan; it
still performs the same secret, network, deployment, and health checks.

### Operations overview and image management

`menu-overview.sh` discovers live services by Docker's stack-namespace label
and lists every service with replica and image state. If the stack does not yet
exist, it reads the generated stack instead. It does not keep a hard-coded API,
WebApp, database, or infrastructure inventory. Interactive terminals color
healthy state green, warnings yellow, and stopped/unhealthy state red while
retaining ASCII status labels for logs and copied output. Under-replicated
services are errors; a running database-management UI is deliberately a
warning because it expands the active administration surface. The same box
shows pending cleanup only for Keycloak users recorded as created by bootstrap.

`menu-shortcuts.sh` defines a cross-repository letter contract: `a` image
audit/security, `b` bootstrap,
`d` deploy, `g` advanced logging, `h` health, `i` images, `l` logs, `p`
database admin, `r` refresh, `s` secrets, `u` update, and `q` exit. Dynamic
numeric entries remain compatibility choices, but capabilities must not change
these letter meanings. `menu_formatting.sh` applies semantic colors only to an
interactive terminal and honors `NO_COLOR`.

`menu-runtime-actions.sh` derives quick-action availability from the selected
profile. Advanced logging switches executable API profiles between their
tracked INFO diagnostics and a WARNING/ERROR-only override; it never enables
DEBUG, SQL echo, or HTTP payload/header logging. Database administration is
available only for local databases with a declared admin UI and supports both
pgAdmin and Mongo Express. Both actions reuse the public-environment
transaction described below. A stopped stack is validated and rendered but
not started implicitly; a running stack is redeployed and health-checked.

`menu-image-actions.sh` reads application-image capabilities from the active
profile and saved root environment. It first separates stable release images
from test profile images, then lets the operator choose one service or all
services. It never synthesizes a deployment tag from the next-release minimum.
The stable selector keeps rollback versions behind `r/x`, groups them by
`MAJOR.MINOR`, and shows nine entries before each cumulative ten-entry `m`
expansion. Enter selects `h` when a highest non-rollback release is available.
`OPERATOR_MENU_LOCALE=de` selects its German catalog; English is the default.
Configured `MAJOR.MINOR.PATCH-test` tags use their clean SemVer base for
ordering. A custom current tag keeps current/highest/exact selection available
without claiming upgrade or rollback ordering. Exact custom Docker tags are
supported after registry/platform proof, except mutable `latest` aliases.
`scripts/registry_image_tool.py` enumerates real stable OCI tags and strict
`MAJOR.MINOR.PATCH-test` tags. `menu-image-test-channel.sh` selects the highest
exact test tag for each chosen repository and excludes `latest-test`. Selected
exact tags are resolved to digests and must declare `linux/amd64`. Stable
all-service mode can choose each repository's own highest tag or their highest
common tag. `menu-image-transaction.sh` stages the public `.env`,
rebuilds through `scripts/build-site-stack.sh`, and calls the common
deploy/health boundary after a single Enter-default confirmation.
Pre-deployment failures restore the old `.env` and generated stack.

`menu-image-audit.sh` owns the shared `a` submenu and ignored public-evidence
cache. `menu-image-audit-profile.sh` converts profile capabilities and live
Swarm digest references into application and infrastructure records. Registry
checks compare application SemVer tags and explicit infrastructure channels;
security checks prefer Docker Scout and fall back to Trivy for fixable
HIGH/CRITICAL CVEs. Docker Scout base recommendations are a separate on-demand
operation because they can be slower and require image provenance. The menu
overview reads cached results only and never performs network/scanner work on
redraw.

`menu-infrastructure-images.sh` extends that submenu with a detailed version
inventory and controlled refresh transaction. Its reusable backup, scanner,
and broad-major-channel gates live in `infrastructure-image-safety.sh`.
`scripts/infrastructure_image_tool.py`
matches live/configured exact digests to recent published tag aliases and
resolves the profile track to a `repository@sha256` target. Numeric tracks keep
their declared major prefix and OS/image family. A refresh scans the exact
target, requires a PostgreSQL backup checkpoint when applicable, writes only a
root `.env` override, and delegates deployment to the existing adapter
transaction. A broad `latest` management channel requires an extra warning.
Exact-target ignores are stored in the public cache and expire on digest
change; CVE evidence is independent. No generic automatic database-backup
action exists until a profile declares a real backup provider and verification
contract.

### `data-dirs.sh`

Creates only the persistent directories required by the selected stack family
and database capabilities. Shared Python API images run as non-root
`10001:10001`, so `/app/logs` and `/app/backups` bind mounts are recursively
assigned to that runtime identity and receive owner read/write access. This
repairs directories previously created by root before any Swarm service is
updated. The deploy fails closed with a permission hint if ownership cannot be
set. A compatible custom API image may override `API_RUNTIME_UID` and
`API_RUNTIME_GID` in the quick-start process environment; no application ID is
hard-coded.

### `keycloak-bootstrap.sh`

Exposes realm bootstrap only when a strict executable profile declares
`auth.provider=keycloak`. It calls
`scripts/keycloak_profile_bootstrap.py`, which updates the existing Keycloak
server through its Admin API. The profile owns the trusted server, defaults,
callback templates, protected identity, realm/mapper policy, application
role options, secret-free temporary test-user defaults, service-account roles,
and Docker-secret target. Active realm, realm booleans, clients, audience,
aggregate test-user lifecycle, and service roots come from the validated
deployment environment.

Before credentials, the operator walks through the active server, realm,
display name, client IDs, service roots, audience, all allowlisted realm
booleans, localization, public SMTP sender fields, and then an installer-style
application-access dialogue. The role catalog comes from the profile; Up/Down
navigates, Space selects or clears, and Enter confirms the exact roles this run
may create and assign. Every
predefined user receives an independent create/update question, another role
selector, and a temporary-password-mode question. An additional-user loop
collects validated public identity and roles without collecting credentials.
When the previous audience matched the previous backend client ID, entering a
new backend ID also changes
the proposed audience default; the audience remains independently editable for
profiles that deliberately use a separate resource identifier. Selections are
validated, persisted to the ignored root `.env`, and used to rebuild
`swarm-stack.yml` before credentials are requested. Shared wizard reruns retain
all of those selections. The server URL remains the tracked credential trust
anchor and cannot be redirected from this password-bearing dialogue. The
administrator username and hidden password prompts remain adjacent.
Immediately after authentication, the bootstrap reads the live Keycloak theme
inventory and presents one numbered menu for each realm theme category. Only
`default` and installed category values are selectable; changed theme
selections are persisted before plan construction.

Independently built WebApp/mobile artifacts must use the selected realm and
client identity.

Changing the realm or backend client while its Docker secret already exists
keeps fail-closed behavior: stop the stack and use the explicit rotation
action so the proven new credential replaces the prior binding.

Secret-safe request tracing is enabled by default and can be explicitly
disabled at its `[Y/n]` prompt or with `--no-debug`. It prints only Keycloak
API surfaces, methods, paths, query-key names, and HTTP status codes—never
request bodies, headers, query values, tokens, passwords, or client secrets.
The administrator access/refresh-token pair remains process-memory-only; long
guided reviews proactively refresh near expiry, and an unexpected HTTP 401
triggers one automatic refresh and retry. Failed phases print sanitized
recovery guidance and, for unexplained server responses, direct the operator
to the existing Keycloak deployment's service logs. Strict read-back errors
also name the exact profile-owned fields that remain drifted.

After authenticated theme selection, the operator sees a sanitized live-state
plan. Selected users missing either the account or its password credential
then receive hidden, confirmation-checked passwords in selected-user order.
Each credential prompt repeats that user's roles and regular/temporary password
mode. Passwords are never persisted or printed. The Enter-default apply
confirmation follows them. Apply success requires Admin API read-back plus
public issuer and JWKS verification.
Selected application roles are reconciled and explicitly scoped into the
public client while its full-scope switch remains disabled. Turning temporary users off does
not delete accounts automatically, and skipped identities never block the
plan. Only successful `create` actions enter the root `.env` cleanup reminder.
The overview keeps that reminder visible until the operator manually removes
those exact users and selects the acknowledgement action. Acknowledgement does
not contact Keycloak, and no shared menu action deletes users. The confidential client
secret moves directly from Keycloak process memory to a client-credentials
proof. When the declared roles grant realm-user access, the token must also
pass a read-only Admin API request. Only then is the same value sent to
`docker secret create` standard input. Docker inspection failures abort instead
of being treated as an absent secret. Existing Docker secrets are reported as
present but unverified because Swarm cannot reveal their value.

Immediately after this run creates or rotates the proven Docker binding, the
interactive CLI offers an opt-in recovery view. The operator selects an
installed nano, vim, or vi editor; the exact value is placed in a mode-0400
`temp_keycloak_secret.txt` inside a mode-0700 private directory, preferably on
memory-backed runtime storage. The editor is launched read-only with swap and
backup behavior disabled where supported. Closing or interrupting the editor
deletes the secret file, any editor sidecars, and the private directory before
the CLI continues. Declining the prompt creates no file. Existing opaque
Docker secrets cannot use this path because their value is unavailable.

Keycloak 26 derives redirect URIs and Web origins from a confidential
service client's root URL. Those browser-only fields are deliberately outside
the backend service-account client's owned verification set because standard
and implicit browser flows remain disabled. Security-relevant service-client
flow, authenticator, scope, root, audience, and role fields remain strict.
Explicit rotation requires the selected stack to be stopped, regenerates and
proves the confidential-client secret in Keycloak, stages a recovery Docker
secret, and then replaces the exact declared Docker secret. Replacement
failures retain and name the recovery object without printing its value.

### `vapid-secrets.sh`

Exposes Web Push key setup only when an exact-name profile has enabled secret
mounts for both `WEB_PUSH_VAPID_PUBLIC_KEY_FILE` and
`WEB_PUSH_VAPID_PRIVATE_KEY_FILE`. It generates one P-256 pair with the host's
`openssl` and `python3`, validates its URL-safe encoding, and creates both
Docker secrets from protected temporary files without logging key values.
Existing pair members are replaced together after the same running-stack
safety gate used by other immutable Docker-secret changes.

### `docker-secrets-menu.sh`

Profiles with `secretsConfig.prefixed=false` use exact declared required,
optional, enabled-capability, and enabled-pgAdmin names. Any profile with a
manually importable secret receives a temporary `secrets.env` action. Shared
templates are generated from `secretsConfig.valueHelp`; a declared specialized
`secretsConfig.template` remains available for structured value shapes.
Keycloak client secrets cannot be entered manually; that action routes to the
shared Keycloak bootstrap. VAPID pair members likewise route to the paired
generator instead of accepting independent values.

Profiles that keep `secretsConfig.prefixed=true` use the historical prefix
adapter. Secret routing is profile-policy-driven, never schema-, renderer-, or
application-driven.

### `profile-secret-file-workflow.sh`

Generates or resolves the profile-owned batch template and passes active
required keys plus an exact secret-name allowlist to the shared importer.
Edited exact-name files cannot create undeclared secrets. Keycloak client
credentials are excluded and remain bootstrap/rotation-only. The protected
temporary values file is deleted whenever the workflow ends, including after
validation failures, editor/import errors, or operator interruption. Saved
restore inputs use a separate explicit retention policy.

### `secret-file-import.sh`

Owns the shared editor, validation, Docker-import, signal handling, and
plaintext cleanup lifecycle. `secret-manager.sh` sources this module to keep
the established `create_secrets_from_env_file` interface available to every
profile. Deletion mode `always` means ephemeral and is enforced on every exit;
`prompt` and `keep` remain available only for explicit saved restore inputs.

### `deploy-stack.sh`

Deploys or updates the selected stack in place with `docker stack deploy`.
Existing stacks are not removed before a normal update, allowing Docker Swarm
to retain prior service specifications. The rendered schema-5 services use
`start-first` updates and `failure_action: rollback`.

`rollback_stack_services()` requests Docker to restore each service's retained
previous specification. It is available from the common deployment menu for
every profile.

### `health-check.sh`

Discovers services through Docker stack labels, checks replica convergence,
shows task and redacted status information, and tests the declared public
health endpoint when applicable.

### `menu_handlers.sh`

Builds menu choices dynamically from the active profile. Keycloak, secrets,
database UI, render, deploy, status, logs, and rollback actions use the same
functions for every app.

### `menu-configuration-actions.sh`

Routes image, replica, database-management, and general configuration changes
through the one shared wizard. It reloads generated public values even when a
later post-configuration action reports failure.

### `menu-restore-actions.sh`

Restores public `.env` data transactionally and immediately rebuilds the
matching stack artifact. Saved secret files remain constrained by the selected
profile's exact/prefixed naming policy.

### Legacy-compatible modules

`user-prompts` retains real Traefik overlay discovery, while
`config-builder`, `admin-ui-compose`, `network-check`, `data-dirs`, `secret-manager`,
`secrets_template_sync`, and compose modules continue to serve schema-3
profiles. New profile-specific branches are forbidden.

## Dependency outline

```text
quick-start
├── site_helpers
├── secret-manager
├── keycloak-bootstrap
├── docker-secrets-menu
├── deploy-stack
├── health-check
└── menu_handlers

setup-wizard
├── site_helpers
├── deployment-profile-prompts
├── deployment-field-help
├── deployment-environment-format
├── deployment-profile-routing
├── deployment-profile-services
├── deployment-profile-inputs
├── legacy-profile-environment
├── executable-profile-wizard
│   └── scripts/site_profile.py
├── deployment-setup-actions
├── docker-secrets-menu
└── keycloak-bootstrap
```

## Adding an application capability

Prefer this order:

1. express the difference in the site-config schema;
2. implement one generic renderer/menu behavior based on that field;
3. prove it with at least two differently named test profiles; and
4. document the new field in `site-configs/README.md`.

Never add `_is_<app>`, `if APP_ID=...`, app-named setup files, or literal
production identity to shared execution code.

## Verification

On Linux:

```bash
bash -n quick-start.sh setup/setup-wizard.sh setup/modules/*.sh scripts/*.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
```

The tests render the tracked new-app template, the real Felix profile, and a
renamed synthetic profile. The synthetic render is the regression proof that
no hidden Felix dependency exists.
