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

For every public profile declaring `services.web: true`, the shared wizard
asks for the WebApp domain before the API domain. A persisted or profile
`routing.domain` remains the API default. If neither provides one, the wizard
derives `api.<entered-web-domain>` after collecting the WebApp answer. Public
API-only profiles continue to ask directly for their API domain.

Memory constraints are opt-in for every profile and service. The canonical
default is `unlimited`, which causes the renderer to omit Docker's
`deploy.resources.limits.memory` block. During setup, pressing Enter on an
`[unlimited]` prompt, or entering `unlimited` or `0`, selects that omission;
an explicit positive byte quantity enables the constraint. Values use bytes,
not bits. The shared parser accepts K/M/G/T (1024-based) and the equivalent
KB/MB/GB/TB or KiB/MiB/GiB/TiB spellings, for example `512M` or `2GiB`.

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
| `database`, `services` | Database contract, exact service topology, digest pins, and audit track tags |
| `image`, `web`, `resources`, `storage` | API/WebApp image, replica, opt-in memory, and storage defaults |
| `release` | Optional release-stack identity, monotonic SemVer floor, and coordinated artifact IDs |
| `pgadmin` | Optional PostgreSQL management-service defaults |
| `cors`, `auth` | Browser-origin, authentication identity, realm policy, and verification contract |
| `environment`, `envKeys` | Exact public runtime environment allowlist |
| `secrets`, `optionalSecrets`, `secretMounts` | Exact Docker secret identifiers and file mounts |
| `secretsConfig` | Exact-versus-prefixed naming, value help, and optional specialized batch template |
| `capabilities` | Optional environment and secret-mount bundles |
| `health` | Expected public health identity |

The shared executable path then:

1. derives fixed application identity, a fixed Keycloak credential trust
   anchor, and editable deployment defaults from the selected JSON;
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
ports, and resource limits are profile defaults rather than a second fixed
identity layer. `storage.dataRoot` may provide a safe absolute recommended
host path. Missing or empty values fall back to the deployment checkout. The
operator may choose another safe absolute path, which the ignored root `.env`
preserves for later reconfiguration.

The generated `.env` persists `DEPLOYMENT_PROFILE_ID`, so an installed clone
reuses its exact site profile for subsequent setup and management actions.
Only an unconfigured clone shows the full profile selector. If that persisted
profile no longer exists, setup fails with an explicit identity error instead
of silently switching to another app.

For Keycloak profiles, `auth.serverUrl`, protected legacy identity, callbacks,
mapper policy, application-role declarations, secret-free temporary test-user
declarations, forbidden users, service-account roles, and the Docker-secret
target remain tracked safety policy. Realm name/display name, the allowlisted
realm booleans, aggregate temporary-test-user lifecycle switch,
frontend/backend client
IDs, audience, and active frontend/API roots are editable deployment values.
The bootstrap persists them to root `.env` and rebuilds the stack. The server
URL is deliberately not an interactive override because the following
administrator password must only be sent to the tracked credential
destination. WebApp/mobile artifacts must be built with the active realm and
client IDs.

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
- API and WebApp images, versions, replicas, and optional memory limits;
- Keycloak realm, clients, callbacks, origins, audience, protected legacy
  identity, exact realm settings, application realm roles, temporary test-user
  declarations, audience-mapper name, bootstrap-reserved usernames, and
  backend service-account client roles;
- required and optional Docker secret identifiers; and
- enabled capability environment and secret mounts.

`routing.traefikNetwork` names the external overlay joined by public services.
`routing.traefikConstraintLabel` separately supplies the label value used by
the Traefik provider to select those services and defaults to
`traefik-public`. These values may be equal, but one must never be inferred
from the other.

For exact-name profiles, `secretsConfig.valueHelp` maps declared manually
editable Docker secret names to concise value guidance. The shared secret menu
generates a protected temporary `secrets.env` directly from those declarations,
while reconciliation-owned Keycloak client secrets are always excluded. A
specialized static `secretsConfig.template` remains available for structured
value shapes such as JSON maps. Every profile import deletes its temporary
values file when the editor/import workflow ends, including after validation
or Docker errors, so readable secret values are never left behind for
correction.

### Optional release coordination

An executable profile can enroll independently built artifacts in one visible
version line:

```json
"release": {
  "stackId": "example-app",
  "versionPolicy": "monotonic-floor",
  "versionFloor": "1.0.0",
  "components": ["api", "web", "android", "ios"]
}
```

`stackId` and component IDs are safe identifiers. `versionFloor` is the stable
`MAJOR.MINOR.PATCH` minimum accepted when the next new artifact is built and
published; `components` must include `api` plus `web` when `services.web` is
enabled. The floor is not a desired deployed version and does not make an
older deployed image stale. The deployment menu derives freshness and update
choices from real registry tags, offers each repository's highest stable tag
or their highest common stable tag, and verifies exact manual input. This
metadata is application-neutral and `_template.json` demonstrates the contract
for new stacks.

Release image tags must be semantic versions. Infrastructure images must be
registry-digest pinned and paired with an explicit comparison channel:
`database.imageTrackTag`, `database.pgadminImageTrackTag`, or
`services.redisImageTrackTag` when the corresponding image exists. A channel
is one exact safe tag such as `16-alpine`, `7-alpine`, or `latest`; it is audit
metadata and never changes the tracked profile digest. Numeric tracks constrain
both the numeric prefix and the image-family suffix: `16-alpine` can select
stable PostgreSQL 16.x Alpine tags but not PostgreSQL 17 or Bookworm, while
`7-alpine` stays on Redis 7.x Alpine. The operator menu resolves a selected
track target to `repository@sha256`, stores that public per-deployment override
in root `.env`, and leaves the reusable profile unchanged. Empty override keys
remain backward-compatible and fall back to the profile pins.

An exact target digest may be snoozed in the ignored audit cache. The snooze is
public operational metadata, expires automatically when the channel digest
changes, and never suppresses vulnerability evidence. PostgreSQL updates also
cross a verified-backup checkpoint; database major migrations are outside the
image-refresh contract. A broad stateless-tool channel such as pgAdmin
`latest` requires separate operator acceptance because it can cross a major
version. Secret values, passwords, tokens, and private keys are forbidden in
site configs and root `.env`.

For `auth.provider=keycloak`, schema 5 also requires:

- `realmDisplayName` and the exact boolean `realmSettings` allowlist;
- `themes`, containing login, account, admin, and email theme defaults; use
  `default` to inherit the corresponding installed server default;
- `localization`, containing internationalization enablement, unique supported
  locales, and a default locale that belongs to that list;
- `emailSender`, containing only public sender and SMTP transport defaults;
  password fields are forbidden;
- `realmRoles`, containing the selectable application-role catalog with unique
  names and descriptions;
- `bootstrapTestUsersEnabled`, which supplies the initial deployment default;
- `bootstrapTestUsers`, containing secret-free identities, exact declared
  application-role assignments, and mandatory production-cleanup markers;
- `audienceMapperName`;
- `forbiddenDefaultUsernames`, which may be empty but must contain unique safe
  names reserved from new automated bootstrap declarations. This field never
  classifies, blocks, or deletes an existing live account; and
- `serviceAccountClientRoles`, grouped by the role-owning Keycloak client.

Bootstrap-user email addresses must also satisfy the shared backend user
contract. Special-use `.invalid`, `.test`, `.local`, and `.localhost`
addresses are rejected because they can authenticate in Keycloak but fail
backend profile creation. Disabled test identities may use the conventional
non-deliverable `example.com` examples shown by `_template.json`; production
identities must use operator-owned addresses and test identities must still be
removed before production activation.

The shared validator rejects Keycloak's `master` realm, built-in managed
client IDs, and any profile that reuses one client ID for both the public
frontend and confidential backend.

The administrator username/password pair is the first interactive boundary.
Invalid credentials or insufficient Admin API permission loop back to that
pair; no configuration question is shown until `/admin/serverinfo` succeeds.
Entering `q` at the username prompt or interrupting credential entry skips the
whole Keycloak bootstrap cleanly so it can be run from the menu later.

After authenticated access is proven, the guided review asks for public realm
identity and booleans, then reads Keycloak's installed theme inventory. Four
numbered single-choice menus offer `default` plus only the live login, account,
admin, or email themes in each category. The server-info metadata also drives
an installer-style locale multiselect for the selected login theme. When the
server default is inherited and its resolved name is not exposed by the Admin
API, the picker says so and offers the union of locales reported by installed
login themes.

The same reusable checkbox control presents the application role catalog.
Up/Down navigates, Space toggles, Enter confirms, and all/none shortcuts are
available. The selected subset becomes the only role set created,
frontend-scoped, and assignable to users during that run; deselection never
silently deletes a live role. Each profile-declared user then has an independent
create/update choice, an exact role multiselect, and a regular-versus-temporary
password-mode choice. Operators may append validated manual bootstrap users
until declining the loop. These detailed choices are secret-free runtime
intent; all selected public settings persist together before the live plan.

If verified-email or password-reset features are selected, SMTP is the
recommended Enter default. Public SMTP values persist to the ignored root
`.env`; an authentication password is requested without echo only after the
authenticated live-state plan and is sent directly to Keycloak. A disabled
`emailSender` profile default means the profile does not alter an existing
realm SMTP map. Interactive setup still requires the operator to configure
SMTP before relying on email-dependent settings. Declining SMTP setup leaves
an existing sender unchanged and does not block unrelated realm/client work;
the plan prints a delivery warning when no sender exists. Profile defaults stay
available for a later run. Entering `none` for optional sender metadata stores
the documented `<empty>` sentinel so a non-empty profile default can be cleared
unambiguously.

The bootstrap authenticates to the existing server, restricts theme selection
to the live server inventory, prints a read-only sanitized plan, applies only
after confirmation, then verifies Admin API read-back, issuer, JWKS,
audience mapper, application roles, temporary users, exact declared
service-account role groups, and bootstrap-owned user state. When a new or updated
authenticated SMTP map is applied, Keycloak's SMTP connection test must also
pass. With the frontend client's full-scope switch disabled, all declared
application roles are added to its dedicated realm-role scope so assigned
roles can reach tokens. Exact service-account verification covers both direct
assignments and the backend client's dedicated role-scope mappings, including
rejection of roles on undeclared clients. A missing client-secret Docker secret is created
only after Keycloak returns the real credential and accepts it in a
client-credentials grant. Profiles declaring a built-in realm-management
user-read role additionally require the resulting token to authorize a
read-only realm-user Admin API request.

The completion summary labels the Docker object identifier as
`dockerSecretName`. For a newly created or rotated binding it also reports the
credential length, a short SHA-256 fingerprint, and an explicit assertion that
the observed value differs from that identifier. These fields provide stable
operator evidence without revealing any credential characters. An existing
Docker secret remains opaque and therefore reports unavailable value evidence
until explicitly rotated.

Test-user passwords never belong in JSON or `.env`. When a selected user or its
password credential is missing, the bootstrap asks for that password without
terminal echo after the authenticated plan, repeats the selected roles and
password mode, and sends the credential directly to Keycloak. Skipping one user
or disabling all test-user management never silently deletes accounts.
Skipped users are not inspected or mutated during that run and therefore do
not block unrelated realm/client reconciliation. Only accounts whose live plan
said `create` and whose apply succeeded enter the root `.env` cleanup reminder.
Existing or self-registered accounts are never inferred to be temporary from
their username. The main menu keeps the reminder visible until the operator
manually deletes those exact accounts in Keycloak and acknowledges that fact;
acknowledgement performs no Keycloak request.
The public operational fields
`KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_PENDING` and
`KEYCLOAK_BOOTSTRAP_USERS_CLEANUP_NAMES` are tool-managed, survive shared setup
reruns, and are excluded from runtime configuration and release fingerprints.
Application roles remain the production authorization contract after those
temporary identities are gone. A disabled realm may be reconciled, but it must
be enabled for a bootstrap run that needs to create or rotate and prove the
confidential client secret.

Every successful interactive run prints the exact realm-settings Admin UI URL
and pauses for a manual review of themes, localization, and email sender state.
The operator must use the UI's **Test connection** action and trigger one real
verification or password-reset email to prove delivery beyond Keycloak's
configuration read-back.

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
| `resources` | Replica defaults and an opt-in memory limit (`unlimited` by default) |
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
