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
- `auth` contains Keycloak identity, protected legacy values, and exact
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
profile values never fall back to renderer-specific raw text prompts.

### `deployment-profile-inputs.sh`

Runs the only deployment dialogue. It normalizes profile defaults and existing
`.env` values, then collects applicable stack, domain, database, proxy/TLS,
Traefik network, service image/tag/replica/memory/port, storage, admin-service,
internal-network, and redirector values.

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
server through its Admin API. Realm, clients, callback URIs, browser origins,
audience, protected identity, service-account client roles, and Docker secret
target all come from the selected profile.

The administrator password is read without echo by Python. The confidential
client secret moves directly from Keycloak process memory to `docker secret
create` standard input. Existing Docker secrets are kept without retrieving
the credential. Explicit rotation requires the selected stack to be stopped,
regenerates the confidential-client secret in Keycloak, and then replaces the
exact declared Docker secret.

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
