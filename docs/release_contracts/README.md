# Felix Swarm release contract

`felix_swarm_contract.v1.json` is a public, secret-free identity and isolation
contract. It records candidate hosts, realm/clients, required service boundary,
and the approval boundary around forwarding the legacy hostname.

It does not define a Felix execution path. Runtime behavior is implemented by
the shared schema-5 site-profile pipeline:

- `site-configs/felix.json` contains Felix values;
- `scripts/site_profile.py` validates and renders any executable profile;
- one shared setup dialogue collects normalized values before
  `renderer.type` selects only the persistence/render adapter;
- Keycloak actions route by `auth.provider`;
- WebApp inclusion routes by `services.web`;
- protected legacy identity and service-account roles route by `auth`;
- exact secrets route by declared secret mounts; and
- deployment, health, logs, and rollback use common stack discovery.

The Felix contract requires both `DB_PASSWORD_FILE` and
`KEYCLOAK_ADMIN_CLIENT_SECRET_FILE`. Their values are Docker secret mount
paths; the underlying credentials never belong in the contract, site profile,
or root `.env`.

Production Keycloak remains the existing `swarm-keycloak` deployment at
`/swarm/administration/keycloak`. The app quick-start menu reconciles its
declared realm and clients through the public Admin API; it never deploys a
second Keycloak and never depends on the local-development `keycloak`
repository.

The contract protects:

- candidate WebApp `felix-app.fe-wi.com`;
- candidate API `api.felix-app.fe-wi.com`;
- candidate realm `felix-new`;
- clients/audience `felix-new-frontend` and `felix-new-backend`;
- legacy host `felix.app.fe-wi.com`;
- protected legacy realms `felix` and `felixappnew`;
- one full-stack service boundary; and
- explicit approval before legacy forwarding.

JSON cannot contain comments, so this README owns safe-editing guidance.
Never add passwords, tokens, private keys, client-secret values, generated
environment dumps, or credential-bearing URLs.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest \
  tests.test_release_orchestration_contract
```
