# Repository Structure

This map describes the current production repository. Historical native
PowerShell deployment files live only under
`old/deprecated-windows-server-deploy-scripts/` and are not part of the active
architecture.

## Top-level ownership

```text
swarm-python-api-template/
├── quick-start.sh
├── .env.example
├── README.md
├── setup/
│   ├── setup-wizard.sh
│   ├── modules/
│   ├── compose-modules/
│   ├── env-templates/
│   └── templates/
├── scripts/
├── site-configs/
├── tests/
├── docs/
└── old/
    └── deprecated-windows-server-deploy-scripts/
```

| Path | Responsibility |
|------|----------------|
| `quick-start.sh` | Production entry point and common operations menu |
| `.env.example` | Public root-environment field reference |
| `setup/` | Shared setup dialogue and shell adapters |
| `scripts/` | Profile validation, deterministic rendering, and Keycloak adapters |
| `site-configs/` | Application-specific capabilities, identity, and defaults |
| `tests/` | Contract, renderer, dialogue, and profile regression tests |
| `docs/` | Architecture, operator, and release-contract documentation |
| `old/` | Archived code that must not be used for production |

## Setup structure

```text
setup/
├── setup-wizard.sh
├── modules/
│   ├── site_helpers.sh
│   ├── deployment-profile-prompts.sh
│   ├── deployment-profile-inputs.sh
│   ├── deployment-profile-routing.sh
│   ├── deployment-profile-services.sh
│   ├── legacy-profile-environment.sh
│   ├── executable-profile-wizard.sh
│   ├── deployment-setup-actions.sh
│   ├── user-prompts.sh
│   ├── menu-configuration-actions.sh
│   ├── menu-restore-actions.sh
│   ├── config-builder.sh
│   ├── admin-ui-compose.sh
│   ├── data-dirs.sh
│   ├── secret-manager.sh
│   ├── profile-secret-file-workflow.sh
│   ├── secrets_template_sync.sh
│   ├── docker-secrets-menu.sh
│   ├── keycloak-bootstrap.sh
│   ├── auth_provider.sh
│   ├── cognito_setup.sh
│   ├── stack-conflict-check.sh
│   ├── network-check.sh
│   ├── deploy-stack.sh
│   ├── health-check.sh
│   ├── menu_handlers.sh
│   ├── menu_formatting.sh
│   ├── git_helpers.sh
│   └── ci-cd-github.sh
├── compose-modules/
│   ├── base.yml
│   ├── api.template.yml
│   ├── footer.yml
│   ├── *-local.yml
│   ├── *-external.yml
│   └── snippets/
├── env-templates/
└── templates/
```

The `deployment-profile-*` modules form one dialogue. Persistence/render
adapters consume its normalized answers and must not prompt independently.

`user-prompts.sh` retains reusable infrastructure discovery such as listing
real Traefik overlay networks. It does not own an app-specific wizard.

## Script structure

```text
scripts/
├── build-site-stack.sh
├── validate-site.sh
├── init-site-data.sh
├── site_profile.py
├── executable_profile.py
├── executable_profile_support.py
├── executable_profile_config_validation.py
├── executable_profile_deployment_validation.py
├── executable_profile_environment.py
├── executable_profile_runtime.py
├── executable_stack_renderer.py
├── keycloak_profile_bootstrap.py
├── keycloak_profile_client.py
├── keycloak_profile_reconciliation.py
├── keycloak_profile_roles.py
└── keycloak_profile_secret_bridge.py
```

- `build-site-stack.sh` dispatches to the profile-declared renderer after
  setup has produced `.env`.
- `site_profile.py` is the version-5.0 command adapter.
- `executable_profile_*` modules validate tracked profile data and
  operator-selected deployment values.
- `executable_stack_renderer.py` renders strict full-stack profiles.
- `keycloak_profile_*` modules update the existing Keycloak server and bridge
  only the declared confidential-client Docker secret.

## Site-config structure

```text
site-configs/
├── README.md
├── _template.json
├── <profile>.json
└── <profile>.json.md
```

The active formats are:

- version 3.0 compatibility profiles;
- version 3.1 compatibility profiles with additive routing/topology fields;
  and
- version 5.0 strict executable profiles.

There is no version 4 profile format. See
[`../site-configs/README.md`](../site-configs/README.md) for field ownership and
safe editing rules.

JSON cannot contain comments. A profile that is created or materially changed
needs a companion `<profile>.json.md` describing ownership, services, secrets,
and safe validation.

## Generated root files

Each production clone owns:

```text
.env              Ignored public deployment-instance values
swarm-stack.yml   Ignored/generated stack definition
```

Secret values are Docker secrets, not generated root files. Setup does not
create a `.setup-complete` marker and does not deploy automatically.

## Dependency flow

```text
site-config
  |
  +-- shared setup dialogue
        |
        +-- normalized answers
              |
              +-- compatibility environment + compose modules
              |
              +-- strict environment + executable renderer
                    |
                    +-- generated .env and swarm-stack.yml
                          |
                          +-- shared operations menu
```

Keycloak, secrets, deployment, health, logs, and rollback are capabilities of
the shared operations layer. They are not renderer-specific user interfaces.

## Change map

| Change | Primary location |
|--------|------------------|
| Add a profile field | `site-configs/README.md`, loader, and validation |
| Change numbered choices | `deployment-profile-prompts.sh` |
| Change stack/domain/database collection | `deployment-profile-inputs.sh` |
| Change proxy/TLS/network collection | `deployment-profile-routing.sh` |
| Change service/resource/storage collection | `deployment-profile-services.sh` |
| Change version-3 persistence | `legacy-profile-environment.sh` |
| Change version-3 rendering | `config-builder.sh` and compose modules |
| Change version-5 validation | `scripts/executable_profile_*_validation.py` |
| Change version-5 rendering | `scripts/executable_stack_renderer.py` |
| Change common deployment actions | `menu_handlers.sh` / `deploy-stack.sh` |

New behavior must be proven against differently named profiles. Shared
execution sources must never contain an application identity condition.

## Platform boundary

The active production flow is Bash on the Linux Swarm host. The repository
does not maintain a native PowerShell setup wizard or paired PowerShell
modules. Use WSL when the active Bash flow must be inspected from Windows.
