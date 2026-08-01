# Architecture Overview

This repository is one reusable Docker Swarm deployment system. A server clone
represents one deployed app stack; the selected file in `site-configs/`
provides that stack's capabilities and defaults.

## Architectural invariant

Shared production code must not branch on an application ID, profile filename,
stack name, domain, realm, client ID, image name, or secret prefix.

All profiles use:

1. one numbered setup dialogue;
2. one normalized set of deployment answers;
3. a profile-declared persistence/render adapter;
4. one capability-driven final-action menu; and
5. one common operations menu for secrets, Keycloak, deploy, status, logs,
   health, and rollback.

Profiles may reference safe repository-relative Compose assets for specialized
topologies. The profile remains the only dispatch boundary: shared scripts
must not contain the application name or hard-code those asset paths.

## Setup flow

```text
quick-start.sh
  |
  +-- setup/setup-wizard.sh
        |
        +-- select site-config
        +-- load profile capabilities and defaults
        +-- choose one shared configuration method
        |     +-- guided numbered questions (default)
        |     +-- generated commented .env editor
        |     +-- unchanged existing .env (fast re-setup)
        +-- normalize one answer contract
        |
        +-- persist through selected adapter
        |     +-- version 3.0/3.1 compatibility environment
        |     +-- version 5.0 strict executable environment
        |
        +-- render through selected adapter
        |     +-- compose-module builder
        |     +-- deterministic executable renderer
        |
        +-- shared final-action menu
              +-- return without external changes
              +-- create data directories
              +-- manage declared Docker secrets
              +-- generate/edit/import temporary secrets.env
              +-- reconcile declared Keycloak identity
              +-- deploy through the common stack action
```

Renderer selection happens only after the dialogue. A renderer is not allowed
to own a second setup wizard or change the operator interaction style.

## Profile-format families

| Version | Purpose | Persistence/rendering |
|---------|---------|-----------------------|
| `3.0` | Original API/database/Redis compatibility profiles | Shared compatibility `.env` writer and compose-module builder |
| `3.1` | Compatibility profiles with exposure/routing metadata or profile-selected complete Compose assets | Same shared dialogue and compatibility adapters |
| `5.0` | Strict full-stack contract with exact services, routing, auth, environment, and secret mounts | Python-validated `.env` writer and deterministic renderer |

There is no version 4 format. Version 5.0 deliberately starts a new major
family because strict validation and exact secret mounts are not a
backward-compatible extension of version 3.

See [`../site-configs/README.md`](../site-configs/README.md) for the canonical
field guide.

## Configuration ownership

| Concern | Owner |
|---------|-------|
| App identity and capabilities | `site-configs/<profile>.json` |
| Operator-selected production values | ignored root `.env` |
| Passwords, tokens, and client secrets | Docker secrets |
| Numbered setup interaction | `deployment-profile-*.sh` modules |
| Accepted-value guidance | `deployment-field-help.sh` |
| Human-readable `.env` structure | `deployment-environment-format.sh` |
| Version-3 persistence | `legacy-profile-environment.sh` |
| Version-3 rendering | `scripts/build-site-stack.sh` and compose modules |
| Version-5 persistence | `executable-profile-wizard.sh` and Python validators |
| Version-5 rendering | `scripts/executable_stack_renderer.py` |
| Realm/client reconciliation | profile-driven Keycloak adapters |
| Deploy, health, logs, and rollback | common operations modules |

Site configs contain safe defaults. The final stack name, domains, image
repositories and versions, replicas, ports, and routing choice are
deployment-instance values written to `.env`. `DATA_ROOT` uses an optional
profile recommendation and otherwise defaults dynamically to the deployment
checkout. Felix recommends `/swarm/prod/felix`, while the shared prompt still
permits an intentional safe absolute override.

For Keycloak profiles, the tracked server URL is the administrator-credential
trust anchor. Realm/display name, managed client IDs, audience, all allowlisted
realm booleans, aggregate temporary-test-user lifecycle, and active service
roots are
validated deployment-instance choices stored in `.env`. When audience and
backend client ID previously matched, changing the backend ID updates the
audience prompt default while retaining an explicit independent override.
Protected legacy identity, the selectable application-role catalog,
secret-free temporary-user defaults, and realm/client policy remain tracked
profile data. Interactive runtime intent chooses a role subset, each declared
user independently, exact per-user roles/password mode, and optional additional
users. Missing test-user passwords are accepted only as hidden runtime input.
Skipping users turns any retained declared account into a production-cleanup
blocker; it never silently deletes identity state.

## Current file structure

```text
quick-start.sh
setup/
  setup-wizard.sh
  modules/
    site_helpers.sh
    deployment-profile-prompts.sh
    deployment-field-help.sh
    deployment-environment-format.sh
    deployment-profile-inputs.sh
    deployment-profile-routing.sh
    deployment-profile-services.sh
    legacy-profile-environment.sh
    executable-profile-wizard.sh
    deployment-setup-actions.sh
    config-builder.sh
    docker-secrets-menu.sh
    keycloak-bootstrap.sh
    menu_handlers.sh
    deploy-stack.sh
    health-check.sh
  compose-modules/
    base.yml
    api.template.yml
    footer.yml
    snippets/
scripts/
  build-site-stack.sh
  site_profile.py
  executable_profile_*.py
  executable_stack_renderer.py
  keycloak_profile_*.py
site-configs/
  README.md
  _template.json
  <profile>.json
  <profile>.json.md
```

The authoritative production workflow is Bash. Historical native PowerShell
deployment scripts are archived under
`old/deprecated-windows-server-deploy-scripts/` and are not maintained. Do not
add a second PowerShell wizard or paired `.ps1` module implementation.

## Renderer adapters

### Compatibility compose modules

Versions 3.0 and 3.1 use the shared legacy environment writer and
`scripts/build-site-stack.sh`. Normal database/proxy combinations are assembled
from reusable fragments. A version-3.1 profile may select complete API/footer
assets for an unusual topology; the declared paths must be safe and
repository-relative.

### Strict executable renderer

Version 5.0 profiles use `scripts/site_profile.py` and its validators to:

1. keep application/authentication identity fixed;
2. accept only declared operator-owned deployment overrides;
3. write a complete public root `.env` atomically;
4. validate exact environment and secret-file contracts;
5. render only profile-declared services; and
6. Compose-check the result before replacing `swarm-stack.yml`.

An optional WebApp is an ordinary `services.web` capability. Felix therefore
does not need a Felix-named setup, renderer, Keycloak, deployment, health, or
rollback module.

## Adding or changing a capability

Use this order:

1. model the difference in the site-config format;
2. add a generic collector/render behavior for that field;
3. prove it with at least two differently named profiles;
4. update `site-configs/README.md`; and
5. update the companion `<profile>.json.md` for non-commentable JSON.

Never add `_is_<app>`, `if APP_ID=...`, or application identity literals to
shared setup and operations sources.

## Security and deployment boundary

- Root `.env` is public configuration and must never contain passwords,
  tokens, private keys, or client-secret values.
- Guided questions and generated `.env` comments share one field-help source;
  both paths feed the same persistence, validation, and rendering adapters.
- Docker secret identifiers and file mounts come from the selected profile.
- Temporary secret files accept only profile-declared manually editable names,
  exclude Keycloak client credentials, and are deleted after full success.
- Keycloak actions update the existing platform through its Admin API; they do
  not deploy another Keycloak instance.
- Setup and rendering do not deploy automatically. Deployment is an explicit
  common-menu action.
- Normal updates use `docker stack deploy` without removing the stack first so
  Swarm retains previous service specifications for rollback.

## Verification

Run the shared validation on Linux:

```bash
bash -n quick-start.sh setup/setup-wizard.sh setup/modules/*.sh scripts/*.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
```

Version-5 profiles can also be checked directly:

```bash
python3 scripts/site_profile.py --root . validate-stack --compose-check
```

Direct commands are validation adapters. Normal operator setup and deployment
remain menu-driven through `./quick-start.sh`.
