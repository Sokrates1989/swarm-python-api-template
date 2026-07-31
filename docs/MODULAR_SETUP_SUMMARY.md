# Modular Setup Summary

This document summarizes the current setup architecture. Earlier revisions of
this repository used separate Bash and PowerShell wizards and a smaller set of
renderer-owned prompts. Those implementations are obsolete; native
PowerShell deployment scripts are archived under
`old/deprecated-windows-server-deploy-scripts/`.

## Outcome

Every deployment profile now enters one numbered, capability-driven Bash
dialogue before persistence or rendering is selected.

```text
profile selection
  -> common input collector
  -> normalized deployment values
  -> profile-declared persistence/render adapter
  -> common final-action menu
  -> common operations menu
```

This separation prevents a new renderer or app profile from introducing a
second operator experience.

## Shared dialogue modules

### `deployment-profile-prompts.sh`

Provides numbered enum/boolean selection and validated free-text primitives.
Pressing Enter accepts the displayed default.

### `deployment-profile-inputs.sh`

Coordinates stack identity, domains, database mode, connection defaults, and
the other capability sections. It also loads an existing root `.env` either
as fast re-setup input or as interactive defaults.

### `deployment-profile-routing.sh`

Collects Traefik/direct routing, TLS ownership, a real discovered Traefik
overlay network, certificate resolver, and applicable published ports.

### `deployment-profile-services.sh`

Collects API and optional WebApp images, semantic versions, replicas, memory,
optional database management, internal networks, and redirector settings. The
shared storage prompt uses an optional profile recommendation, falls back to
the deployment checkout root, and accepts an explicit safe absolute host path.

## Persistence and rendering

### Versions 3.0 and 3.1

`legacy-profile-environment.sh` writes the compatibility root `.env`.
`scripts/build-site-stack.sh` and `config-builder.sh` assemble reusable Compose
modules. A version-3.1 profile may select safe repository-relative complete
Compose assets for a specialized topology.

### Version 5.0

`executable-profile-wizard.sh` is a prompt-free adapter. It passes the common
answers to `scripts/site_profile.py`, whose validators write the public root
`.env` and whose deterministic renderer builds and Compose-checks
`swarm-stack.yml`.

Version 5.0 fixes application and authentication identity while allowing
deployment-instance values such as stack name, domains, image repositories
and tags, replicas, and ports to use profile defaults that the operator can
change. `DATA_ROOT` uses an optional `storage.dataRoot` recommendation or the
deployment repository root as its dynamic fallback.

There is no version 4 profile format. Version 5.0 is a separate strict contract
family, not an incremental version-3 extension.

## Capability-driven actions

`deployment-setup-actions.sh` builds one final-action menu. Entries appear only
when the selected profile declares the required capability:

- data-directory preparation;
- Docker secret management;
- Keycloak realm/client reconciliation; and
- deployment through the shared stack action.

The main quick-start menu similarly discovers active profile services for
status, logs, health, update, scale, and rollback behavior.

## Application boundaries

`site-configs/<profile>.json` is the only app-specific dispatch boundary. A
profile supplies:

- service topology and database mode;
- public, direct, or internal exposure;
- routing and service defaults;
- optional WebApp and management services;
- authentication identity and allowed callbacks/origins;
- exact required and optional secret identifiers; and
- optional safe paths to specialized Compose assets.

Shared scripts must never branch on `APP_ID` or a profile filename. A WebApp is
an ordinary `services.web` capability; it does not justify a separate app
wizard.

## Generated and secret state

The setup wizard writes:

```text
.env              Public deployment-instance values
swarm-stack.yml   Generated stack definition
```

It does not create a completion marker and does not deploy without the
operator selecting the explicit shared action.

Secret values stay in Docker secrets. Site configs and root `.env` contain
only public values and secret identifiers.

## Platform status

The Linux/Bash flow is authoritative. There is no maintained
`setup-wizard.ps1` or set of paired PowerShell modules. From Windows, use WSL
to execute the Bash flow when local inspection is needed.

## Extension checklist

1. Express the difference in the site-config format.
2. Implement one generic behavior for that field.
3. Keep renderer adapters prompt-free.
4. Test with at least two differently named profiles.
5. Update `site-configs/README.md` and relevant companion profile docs.
6. Reject any application-name branch in shared execution sources.

## Verification

```bash
bash -n quick-start.sh setup/setup-wizard.sh setup/modules/*.sh scripts/*.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
```
