# Felix candidate site profile

## Purpose and ownership

`felix.json` is the Swarm-owned, versioned and secret-free deployment profile
for the candidate Felix Backend and WebApp stack. It deliberately targets
stack `felix-new`, API host `api.felix-app.fe-wi.com`, and WebApp host
`felix-app.fe-wi.com`; it must never claim the legacy
`felix.app.fe-wi.com` deployment.

Schema `4.0` makes `environment`, `envKeys`, `secretMounts`, and capability
declarations executable inputs to the strict Felix renderer. `envKeys` must
exactly enumerate the base environment plus active secret-file fields. Enabling
AI or Web Push also requires adding that capability's declared environment and
secret-file fields to `envKeys`.

## Images and services

- The Felix API uses the prepared RLS-13 publication target `0.1.1`; `latest`
  and unversioned tags are
  rejected.
- The upstream version tag may be republished intentionally. Strict preflight
  resolves its current registry digest, and deployment uses that immutable
  digest rather than following later tag changes.
- PostgreSQL 16, Redis 7, and optional pgAdmin are pinned by registry digest.
- PostgreSQL can run in the same stack or use operator-supplied external
  connection metadata; passwords remain Docker secrets in both modes.
- Optional pgAdmin is available only with local PostgreSQL and Traefik. It has
  its own file-backed Docker secret and persistent directory. Its pinned
  multi-platform digest was resolved from the explicit upstream `9.15.0` tag;
  the data-directory action assigns documented container ownership `5050:5050`.
- The Traefik router attaches only to `api.felix-app.fe-wi.com`.
- Proxy SSL mode keeps TLS termination at the existing upstream proxy and
  forwards `X-Forwarded-Proto=https` to the candidate API.

The profile contains no passwords, tokens, private keys, or client-secret
values. Docker secret names are identifiers only.

## Keycloak and capabilities

The public client is `felix-new-frontend`. The API audience and least-privilege
administration client are both `felix-new-backend`. Browser and Android
callbacks remain exact: `https://felix-app.fe-wi.com/auth/callback` and
`felixkc:/callback`.

AI chat and durable Web Push are disabled by default. When enabled, their
private material is mounted from the optional Docker secrets declared here;
direct secret environment variables remain forbidden.

## Safe editing and validation

Keep the JSON strict and duplicate-free. Do not add `${...}`,
`XXX_CHANGE...`, `###...`, wildcard origins, localhost endpoints, direct
secret values, or deployment aliases such as `latest`.

Use `./quick-start.sh` and select the setup wizard plus
**Felix Backend and WebApp**. It writes the ignored root `.env` and renders the
stack. The direct commands below are validation adapters, not the normal
operator workflow:

```bash
python3 scripts/felix_site_profile.py validate
python3 scripts/felix_site_profile.py render --compose-check
```

The render writes the ignored root `swarm-stack.yml`. It does not create Docker
secrets and does not deploy or modify either Keycloak realm.
