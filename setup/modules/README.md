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
- `secrets`, `optionalSecrets`, and `secretMounts` control exact Docker
  secrets; and
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
actions appear only when the profile declares those capabilities.

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
booleans, and then an installer-style application-access dialogue. The role
catalog comes from the profile; Up/Down navigates, Space selects or clears,
and Enter confirms the exact roles this run may create and assign. Every
predefined user receives an independent create/update question, another role
selector, and a temporary-password-mode question. An additional-user loop
collects validated public identity and roles without collecting credentials.
When the previous audience
matched the previous backend client ID, entering a new backend ID also changes
the proposed audience default; the audience remains independently editable for
profiles that deliberately use a separate resource identifier. Selections are
validated, persisted to the ignored root `.env`, and used to rebuild
`swarm-stack.yml` before credentials are requested. Shared wizard reruns retain
all of those selections. The server URL remains the tracked credential trust
anchor and cannot be redirected from this password-bearing dialogue. The
administrator username and hidden password prompts remain adjacent.
Independently built WebApp/mobile artifacts must use the selected realm and
client identity.
Changing the realm or backend client while its Docker secret already exists
keeps fail-closed behavior: stop the stack and use the explicit rotation
action so the proven new credential replaces the prior binding.

The operator may enable secret-safe debug tracing. It prints only Admin API
methods, paths, query-key names, and HTTP status codes—never request bodies,
headers, query values, tokens, passwords, or client secrets. Strict read-back
errors also name the exact profile-owned fields that remain drifted.

After authentication, the operator sees a sanitized live-state plan. Selected
users missing either the account or its password credential then receive
hidden, confirmation-checked passwords in selected-user order. Each credential
prompt repeats that user's roles and regular/temporary password mode. Passwords
are never persisted or printed, followed by the Enter-default apply
confirmation. Apply success requires Admin API read-back plus public issuer
and JWKS verification.
Selected application roles are reconciled and explicitly scoped into the
public client while its full-scope switch remains disabled. Turning temporary users off does
not delete accounts automatically: retained test identities block the plan
until the operator removes them, and the dialogue warns, "Once you enter
production mode, remember to delete those users." The confidential client
secret moves directly from Keycloak process memory to a client-credentials
proof. When the declared roles grant realm-user access, the token must also
pass a read-only Admin API request. Only then is the same value sent to
`docker secret create` standard input. Docker inspection failures abort instead
of being treated as an absent secret. Existing Docker secrets are reported as
present but unverified because Swarm cannot reveal their value.

Keycloak 26 derives redirect URIs and Web origins from a confidential
service client's root URL. Those browser-only fields are deliberately outside
the backend service-account client's owned verification set because standard
and implicit browser flows remain disabled. Security-relevant service-client
flow, authenticator, scope, root, audience, and role fields remain strict.
Explicit rotation requires the selected stack to be stopped, regenerates and
proves the confidential-client secret in Keycloak, stages a recovery Docker
secret, and then replaces the exact declared Docker secret. Replacement
failures retain and name the recovery object without printing its value.

### `docker-secrets-menu.sh`

Profiles with `secretsConfig.prefixed=false` use exact declared required,
optional, enabled-capability, and enabled-pgAdmin names. A declared
`secretsConfig.template` also enables batch creation through `secrets.env`.
Keycloak client secrets cannot be entered manually; that action routes to the
shared Keycloak bootstrap.

Profiles that keep `secretsConfig.prefixed=true` use the historical prefix
adapter. Secret routing is profile-policy-driven, never schema-, renderer-, or
application-driven.

### `profile-secret-file-workflow.sh`

Resolves the profile-owned batch template and passes an active secret-name
allowlist to the shared importer. Edited exact-name files cannot create Docker
secrets that are absent from the selected profile. Keycloak client credentials
are excluded and remain bootstrap/rotation-only.

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
