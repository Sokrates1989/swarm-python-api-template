# Felix Swarm Release Contract

## Purpose and ownership

`felix_swarm_contract.v1.json` is the Swarm repository's public, secret-free
release-orchestration export. It freezes candidate versus legacy deployment
identity, environment and secret-file field names, digest-bound image policy,
and the approval boundary around forwarding the old hostname.

The Swarm repository owns these values. Cross-repository tooling may read the
file but must not write or materialize secrets from it.

Production Keycloak is owned by the already deployed
`D:\Development\Code\swarm\swarm-keycloak` repository at
`/swarm/administration/keycloak`. The local-development
`D:\Development\Code\keycloak` repository and a separate `/swarm/keycloak`
checkout are not production dependencies.

## Structure

- `candidate` identifies `felix-app.fe-wi.com`, realm `felix-new`, and client
  `felix-new-frontend`, plus API audience and least-privilege administration
  client `felix-new-backend`.
- `legacyProtection` protects `felix.app.fe-wi.com` plus possible legacy realms
  `felix` and `felixappnew`.
- `requiredEnvironmentFields` names public runtime settings.
- `requiredSecretFileFields` names mounted secret-file settings.
- `deploymentBoundary` keeps candidate and legacy routers distinct and makes
  old-host forwarding an explicit, reversible cutover action.
- `productionKeycloakOwner` records the non-secret production repository/path
  boundary without embedding credentials or invoking another checkout.

## Safe editing

Keep the fixture strict JSON. Never store passwords, tokens, client secrets,
private keys, credential-bearing URLs, or generated stack environment dumps.
Intentional public changes must update this fixture, its tests, and the Flutter
snapshot together.

Run:

```powershell
python tests/test_release_orchestration_contract.py
```
