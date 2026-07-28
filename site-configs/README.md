# Deployment profiles

`site-configs/` is the only application-specific production configuration
boundary. Setup, rendering, secrets, Keycloak reconciliation, deployment,
health, logs, and rollback code must never branch on an app ID or profile
filename.

The setup wizard lists these JSON files and routes by declared schema
capabilities. An application can differ by database, WebApp, image, routing,
authentication, secret mounts, resources, or optional capabilities only by
declaring those differences here.

## Schema 5 executable profiles

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

The shared executable path then:

1. derives fixed identity and editable defaults from the selected JSON;
2. writes the ignored, public-only root `.env`;
3. validates `environment`, `envKeys`, and file-backed secret mounts;
4. renders the complete `swarm-stack.yml`;
5. includes services strictly according to `services`;
6. exposes Keycloak actions only when `auth.provider` is `keycloak`; and
7. uses exact declared secret names without deriving an app-specific prefix.

`services.web` controls the optional WebApp service. When true, `web.image`,
`web.resources`, and the `routing.web*` fields define that service. No code
change or app-specific wizard is required. Felix uses this ordinary mechanism
to add its Flutter WebApp alongside API, Redis, and the selected PostgreSQL
mode.

The same rule applies to:

- `services.redis` and `services.database`;
- local versus external database modes;
- optional pgAdmin;
- Traefik network/certificate resolver versus direct published ports,
  including a direct pgAdmin port;
- API and WebApp images, versions, replicas, and memory;
- Keycloak realm, clients, callbacks, origins, audience, protected legacy
  identity, and backend service-account client roles;
- required and optional Docker secret identifiers; and
- enabled capability environment and secret mounts.

Release image tags must be semantic versions. Infrastructure images must be
registry-digest pinned. Secret values, passwords, tokens, and private keys are
forbidden in site configs and root `.env`.

`_template.json` is the canonical schema-5 new-app starting point. Copy it to
`<profile-id>.json`, replace its example public identity and image values, add
the companion `<profile-id>.json.md`, and validate through the shared setup
flow. Do not create an app-named setup script, renderer, Keycloak helper,
secret template, or operations menu.

## Older profiles

Schema 3 profiles continue through the reusable compose-module path while they
are migrated. That compatibility path is also profile-driven; it must not gain
app-name conditions. New full-stack profiles should use schema 5.

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
