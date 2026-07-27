# Felix candidate site profile

## Purpose and ownership

`felix.json` is the Swarm-owned, versioned and secret-free deployment profile
for the candidate Felix backend. It deliberately targets stack `felix-new` and
API host `api.felix-app.fe-wi.com`; it must never be changed to claim the
legacy `felix.app.fe-wi.com` deployment.

Schema `4.0` makes `environment`, `envKeys`, `secretMounts`, and capability
declarations executable inputs to the strict Felix renderer. `envKeys` must
exactly enumerate the base environment plus active secret-file fields. Enabling
AI or Web Push also requires adding that capability's declared environment and
secret-file fields to `envKeys`.

## Images and services

- The Felix API uses release tag `0.1.0`; `latest` and unversioned tags are
  rejected.
- PostgreSQL 16 and Redis 7 are pinned by registry digest.
- Local PostgreSQL is the only accepted database mode for the first candidate
  production deployment.
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
secret values, or mutable image tags.

Validate and render only after creating the ignored public `prod.env`:

```bash
python3 scripts/felix_site_profile.py validate
python3 scripts/felix_site_profile.py render --compose-check
```

The render writes the ignored root `swarm-stack.yml`. It does not create Docker
secrets and does not deploy or modify either Keycloak realm.
