# Deployment profiles

`site-configs/` is the only application-specific production configuration
boundary. Setup, rendering, secrets, Keycloak reconciliation, deployment,
health, logs, and rollback code must never branch on an app ID or profile
filename.

The setup wizard lists these JSON files and routes by declared schema
capabilities. An application can differ by database, WebApp, image, routing,
authentication, secret mounts, resources, or optional capabilities only
through declarations here. A compatibility profile may reference safe
repository-relative Compose assets for a specialized topology; the profile
remains the only dispatch boundary and shared scripts must not hard-code the
asset or application name.

## Version map

The repository currently accepts these profile-format versions:

| Version | Renderer family | Purpose |
|---------|-----------------|---------|
| `3.0` | Compatibility compose modules | Original API/database/Redis profiles |
| `3.1` | Compatibility compose modules | Exposure/routing metadata and optional profile-selected complete Compose assets |
| `5.0` | Strict executable renderer | Validated full-stack services, routing, auth, exact secret mounts, and deterministic rendering |

There is no version 4 profile format. Version 5.0 intentionally starts a new
major family because its strict executable contract is not a
backward-compatible extension of version 3.

The `$schema: "site-config-schema"` entry is a repository marker, not a
resolvable external JSON Schema URI. Validation is currently implemented by
the shared shell loader for compatibility profiles and by
`scripts/executable_profile_config_validation.py` for version 5.0. This README
is the canonical field-level format guide until a formal JSON Schema is added.

## Version 5.0 executable profiles

Set:

```json
{
  "version": "5.0",
  "renderer": {
    "type": "executable",
    "strict": true
  }
}
```

Version 5.0 owns these main objects:

| Field | Responsibility |
|-------|----------------|
| `appId`, `name`, `kind` | Application identity and display metadata |
| `renderer` | Strict executable adapter selection |
| `stack` | Default stack name, family, role, and primary service |
| `exposure`, `routing` | Allowed public/direct exposure and safe routing defaults |
| `database`, `services` | Database contract and exact service topology |
| `image`, `web`, `resources`, `storage` | API/WebApp image and deployment defaults |
| `pgadmin` | Optional PostgreSQL management-service defaults |
| `cors`, `auth` | Browser-origin, authentication identity, realm policy, and verification contract |
| `environment`, `envKeys` | Exact public runtime environment allowlist |
| `secrets`, `optionalSecrets`, `secretMounts` | Exact Docker secret identifiers and file mounts |
| `secretsConfig` | Exact-versus-prefixed naming and optional batch-entry template |
| `capabilities` | Optional environment and secret-mount bundles |
| `health` | Expected public health identity |

The shared executable path then:

1. derives fixed application/authentication identity and editable deployment
   defaults from the selected JSON;
2. writes the ignored, public-only root `.env`;
3. validates `environment`, `envKeys`, and file-backed secret mounts;
4. renders the complete `swarm-stack.yml`;
5. includes services strictly according to `services`;
6. exposes Keycloak actions only when a strict executable profile declares
   `auth.provider` as `keycloak`; and
7. follows `secretsConfig.prefixed` instead of inferring naming from renderer
   or schema.

All schemas first pass through the same numbered setup dialogue. Renderer
selection happens only after its normalized answers have been collected.
Stack names, applicable domains, service image repositories/tags, replicas,
ports, resource limits, and storage paths are profile defaults rather than a
second fixed identity layer.

`services.web` controls the optional WebApp service. When true, `web.image`,
`web.resources`, and the `routing.web*` fields define that service. No code
change or app-specific wizard is required. Felix uses this ordinary mechanism
to add its Flutter WebApp alongside API, Redis, and the selected PostgreSQL
mode.

The same rule applies to:

- `services.redis` and `services.database`;
- local versus external database modes;
- optional pgAdmin;
- Traefik overlay network, provider constraint label, and certificate resolver
  versus direct published ports,
  including a direct pgAdmin port;
- API and WebApp images, versions, replicas, and memory;
- Keycloak realm, clients, callbacks, origins, audience, protected legacy
  identity, exact realm settings, audience-mapper name, forbidden default
  usernames, and backend service-account client roles;
- required and optional Docker secret identifiers; and
- enabled capability environment and secret mounts.

`routing.traefikNetwork` names the external overlay joined by public services.
`routing.traefikConstraintLabel` separately supplies the label value used by
the Traefik provider to select those services and defaults to
`traefik-public`. These values may be equal, but one must never be inferred
from the other.

Release image tags must be semantic versions. Infrastructure images must be
registry-digest pinned. Secret values, passwords, tokens, and private keys are
forbidden in site configs and root `.env`.

For `auth.provider=keycloak`, schema 5 also requires:

- `realmDisplayName` and the exact boolean `realmSettings` allowlist;
- `audienceMapperName`;
- `forbiddenDefaultUsernames`, which may be empty but must contain unique safe
  names; and
- `serviceAccountClientRoles`, grouped by the role-owning Keycloak client.

The shared validator rejects Keycloak's `master` realm, built-in managed
client IDs, and any profile that reuses one client ID for both the public
frontend and confidential backend.

The bootstrap authenticates to the existing server, prints a read-only
sanitized plan, applies only after confirmation, then verifies Admin API
read-back, issuer, JWKS, audience mapper, exact declared role groups, and
forbidden-user absence. Exact role verification covers both direct
service-account assignments and the backend client's dedicated role-scope
mappings, including rejection of roles on undeclared clients. A missing
client-secret Docker secret is created only after Keycloak returns the real
credential and accepts it in a client-credentials grant. Profiles declaring a
built-in realm-management user-read role additionally require the resulting
token to authorize a read-only realm-user Admin API request.

`_template.json` is the canonical schema-5 new-app starting point. Copy it to
`<profile-id>.json`, replace its example public identity and image values, add
the companion `<profile-id>.json.md`, and validate through the shared setup
flow. Do not create an app-named setup script, renderer, Keycloak helper,
or operations menu. Declare a profile-specific secret template only when the
profile’s secret value shapes genuinely differ from the shared template.

## Versions 3.0 and 3.1 compatibility profiles

Version 3.0 profiles continue through the reusable compose-module path while
they are migrated. Version 3.1 is an additive compatibility revision for
profiles that declare exposure/routing details or specialized complete
topology assets. Both versions use the same shared numbered dialogue and the
same compatibility environment adapter. That path is profile-driven and must
not gain app-name conditions. New full-stack profiles should use version 5.0.

Version 3.0 uses these core fields:

| Field | Responsibility |
|-------|----------------|
| `appId`, `name`, `description` | Application identity and operator label |
| `database.type`, `database.defaultMode` | Database engine and mode default |
| `services` | Redis/database capability flags |
| `image` | API image repository and tag default |
| `resources` | Replica and memory defaults |
| `adminUI` | Optional database-management capability |
| `secrets`, `envKeys` | Compatibility secret identifiers and runtime keys |

Version 3.1 may additionally declare `kind`, `stack`, `exposure`, `routing`,
`networking`, `redirector`, `renderer`, and `secretsConfig`. These additions
describe internal/public routing, stack/service identity, redirect behavior,
exact-versus-prefixed secret handling, or specialized Compose assets without
changing the shared dialogue.

A version-3.1 profile with a specialized complete topology may declare:

```json
{
  "renderer": {
    "type": "compose-modules",
    "strict": false,
    "apiTemplate": "setup/compose-modules/example-api.yml",
    "footerTemplate": "setup/compose-modules/example-footer.yml"
  }
}
```

The two paths must be safe repository-relative files. This selects compose
assets only; it does not select another setup dialogue. Shared scripts must
never contain the profile ID or those app-specific filenames.

## Safe editing

JSON does not support comments. Add or update `<profile>.json.md` when a
profile is created or materially changed. The companion document should cover
purpose, ownership, services, important fields, secret boundaries, and safe
validation.

Validate an already configured executable profile with:

```bash
python3 scripts/site_profile.py --root . validate-stack --compose-check
```

Normal operator use remains `./quick-start.sh`; direct commands are validation
adapters, not alternate deployment workflows.
