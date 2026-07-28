# Setup modules

These modules implement the reusable setup and operations menu. The
PowerShell launcher enters the authoritative Bash workflow through WSL, so
menu-only modules can be Bash-only.

## Architectural invariant

Production modules must not branch on an application ID, profile filename,
stack name, domain, realm, client ID, image name, or secret prefix. Every app
uses the same menu. Differences are selected from `site-configs/<profile>.json`
through schema and capability fields.

In particular:

- `renderer.type` selects the rendering strategy;
- `services` selects API, WebApp, Redis, and database services;
- `database` selects engine, local/external mode, images, and optional admin
  UI;
- `routing` and `exposure` select Traefik network/resolver or direct ports;
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

### `executable-profile-wizard.sh`

Runs the common schema-5 setup:

1. displays profile-owned identity;
2. collects operator-owned database, proxy/TLS, image version, resource,
   storage, WebApp, and optional pgAdmin values;
3. calls `scripts/site_profile.py` to atomically write root `.env`;
4. renders and Compose-validates `swarm-stack.yml`; and
5. offers data-directory, Docker-secret, and Keycloak actions.

It never deploys automatically and never reads a secret value.

### `keycloak-bootstrap.sh`

Exposes realm bootstrap only when `auth.provider=keycloak`. It calls
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

For executable profiles, lists and manages exact profile-declared required,
optional, enabled-capability, and enabled-pgAdmin secrets. Keycloak client
secrets cannot be entered manually; that action routes to the shared Keycloak
bootstrap.

Older schema profiles retain the historical prefixed-secret flow while they
are migrated. This compatibility distinction is schema-driven, not app-driven.

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

### Legacy-compatible modules

`user-prompts`, `config-builder`, `network-check`, `data-dirs`,
`secret-manager`, `secrets_template_sync`, and compose modules continue to
serve schema-3 profiles. New profile-specific branches are forbidden.

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
├── executable-profile-wizard
│   ├── scripts/site_profile.py
│   ├── data-dirs
│   ├── docker-secrets-menu
│   └── keycloak-bootstrap
└── legacy schema modules
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
