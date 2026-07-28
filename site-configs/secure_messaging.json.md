# Secure Messaging deployment profile

## Purpose and ownership

`secure_messaging.json` describes an internal-only API stack. It uses the same
setup dialogue, environment writer, operations menu, and deployment actions as
every other schema-3 compatibility profile.

The profile is intentionally different through data:

- `exposure.type: internal` skips public domain, Traefik, TLS, and published
  port questions;
- `database.type: none` skips database and management-service questions;
- `networking.internalNetwork` supplies the internal overlay-network default;
- `secretsConfig.prefixed: false` retains exact externally managed secret
  names;
- `secretsConfig.template` enables the shared batch-entry menu for those
  literal names; and
- `renderer.apiTemplate` plus `renderer.footerTemplate` select complete
  compose modules for this specialized service topology.

## Renderer modules

The declared compose-module paths are repository-relative and validated before
use. Shared setup and build code does not contain the profile ID or module
filenames. Another internal service can use the same mechanism by declaring
its own modules in its site config.

The YAML modules may contain service-specific environment and secret mappings;
that application detail belongs in the declared assets, not in shared
orchestration code.

## Safe editing

Do not add secret values to this JSON. The `secrets` array contains identifiers
only. Use **Manage Docker secrets → Create secrets from the profile template**
instead of an application-specific script. Keep internal service/network names
aligned with the declared compose modules, and run the normal quick-start setup
plus stack rebuild after changing the profile.
