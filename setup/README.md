# Setup Directory

This directory contains the authoritative Bash setup dialogue, persistence
adapters, Compose assets, and production operations modules.

Normal operator use starts at the repository root:

```bash
./quick-start.sh
```

Choose **Run setup wizard**, select a site profile, and follow the same
numbered dialogue for every profile. Running `./setup/setup-wizard.sh`
directly is supported for setup validation, but it is not a separate workflow.

## What setup creates

The wizard generates these ignored deployment-instance artifacts at the
repository root:

```text
.env              Public deployment configuration
swarm-stack.yml   Rendered Docker Swarm stack
```

It does not create a `.setup-complete` marker and does not deploy
automatically. After rendering, one shared final-action menu lets the operator
return, prepare data directories, manage declared Docker secrets, reconcile a
declared Keycloak realm, or invoke the common deployment action.

Passwords, tokens, private keys, and client-secret values never belong in
`.env` or `swarm-stack.yml`.

## One setup dialogue

`setup-wizard.sh` coordinates one profile-independent sequence:

1. select a JSON profile from `site-configs/`;
2. load its capabilities and safe defaults;
3. collect applicable stack, domain, database, proxy/TLS, network, service,
   image, resource, port, storage, and admin-service values; storage uses an
   optional profile recommendation or the deployment checkout root;
4. write root `.env` through the selected persistence adapter;
5. render and Compose-check `swarm-stack.yml` through the selected renderer;
   and
6. show the shared final-action menu.

Enum and boolean questions are numbered. Pressing Enter accepts the displayed
default. Questions are skipped only when the selected profile declares that a
capability does not apply.

If `.env` already exists, the wizard offers:

1. use its values and skip the dialogue for a fast re-render; or
2. answer interactively with existing values offered as defaults.

An existing `.env` is accepted only for its recorded deployment profile.

## Module responsibilities

```text
setup/
  setup-wizard.sh
  modules/
    site_helpers.sh
    deployment-profile-prompts.sh
    deployment-profile-inputs.sh
    deployment-profile-routing.sh
    deployment-profile-services.sh
    legacy-profile-environment.sh
    executable-profile-wizard.sh
    deployment-setup-actions.sh
    user-prompts.sh
    menu-configuration-actions.sh
    menu-restore-actions.sh
    config-builder.sh
    admin-ui-compose.sh
    data-dirs.sh
    docker-secrets-menu.sh
    profile-secret-file-workflow.sh
    secret-manager.sh
    keycloak-bootstrap.sh
    menu_handlers.sh
    deploy-stack.sh
    health-check.sh
  compose-modules/
  env-templates/
  templates/
```

- `site_helpers.sh` discovers profiles and loads profile/root-environment
  values.
- `deployment-profile-prompts.sh` owns numbered choices and validated text
  input. Every public-domain question automatically includes the shared
  subdomain-creation guide, including API, WebApp, and database-management
  service domains.
- `deployment-profile-inputs.sh` coordinates the only deployment dialogue.
- `deployment-profile-routing.sh` owns proxy, TLS, distinct Traefik overlay
  network/provider-label settings, and direct-port questions.
- `deployment-profile-services.sh` owns images, resources, the profile-or-
  checkout-default storage path, WebApp, admin-service, internal-network, and
  redirector questions.
- `legacy-profile-environment.sh` persists version-3.0/3.1 compatibility
  answers.
- `executable-profile-wizard.sh` is the prompt-free version-5.0 persistence
  and render adapter.
- `deployment-setup-actions.sh` owns the capability-driven final-action menu.
- `menu-configuration-actions.sh` routes image, replica, admin-service, and
  general changes back through the same setup dialogue and reloads its output.
- `menu-restore-actions.sh` binds restored `.env` values to an immediately
  regenerated stack and routes saved secret values through profile policy.
- `config-builder.sh` and Compose modules render compatibility profiles.
- `admin-ui-compose.sh` renders a profile-selected database-management
  service without adding service-specific branches to the shared builder.
- `profile-secret-file-workflow.sh` constrains saved secret files to names
  declared by the selected profile before Docker is mutated.
- Secret, Keycloak, deploy, health, logs, and rollback modules are shared by
  the quick-start operations menu.

Detailed module contracts are documented in
[`modules/README.md`](modules/README.md).

## Profile-driven differences

Application-specific dispatch belongs in `site-configs/<profile>.json`.
Shared setup code must never branch on an app ID or profile filename.

A profile can:

- select local or external database mode;
- enable Redis, a database, WebApp, or management service;
- choose public Traefik routing, direct ports, or internal-only exposure;
- declare service defaults and exact Docker secret identifiers;
- declare Keycloak identity and capabilities; and
- reference safe repository-relative Compose assets for a specialized
  compatibility topology.

The profile selects those assets; shared scripts do not contain
application-specific filenames.

## Platform support

The production implementation is Bash and is intended for the Linux Swarm
host. Native PowerShell deployment scripts are archived under
`old/deprecated-windows-server-deploy-scripts/` and are not maintained.

Do not invoke the archived `setup-wizard.ps1` and do not add parallel `.ps1`
module implementations. When inspecting the production flow from Windows, use
WSL to run the Bash entry point.

## Validation

On Linux:

```bash
bash -n setup/setup-wizard.sh setup/modules/*.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
```

For an already configured strict executable profile:

```bash
python3 scripts/site_profile.py --root . validate-stack --compose-check
```

For troubleshooting, inspect the selected profile, root `.env`, and rendered
`swarm-stack.yml` before invoking deployment from the common quick-start menu.
