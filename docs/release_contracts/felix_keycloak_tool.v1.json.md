# Felix canonical Keycloak tool pin

## Purpose and ownership

`felix_keycloak_tool.v1.json` pins the Swarm adapter to the exact canonical
Keycloak CLI source revision proven by RLS-11. The Keycloak repository owns
realm/client policy and mutations; this deployment repository only validates
the pin and delegates explicit operator actions.

## Structure

- `toolVersion`, `sourceRepository`, `sourceCommit`, and `entrypoint` identify
  the immutable canonical interface.
- Candidate realm/client fields prevent an adapter from being reused for a
  protected legacy identity.
- `dockerSecretName` is a public Docker secret identifier, never its value.

## Safe editing

Update the pin only after the canonical Keycloak contract, mocked tests, and
pinned disposable-Keycloak integration test pass at the new commit. Never add
an administrator password, access token, confidential client secret, Docker
secret value, or credential-bearing URL.

The adapter requires a clean canonical checkout at the exact commit. It never
clones, pulls, checks out, or updates that repository implicitly.
