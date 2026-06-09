# Nginx-Only Deployment Enablement Plan

## 1. Purpose

This document defines the phased implementation plan for enabling Nginx-only deployments inside `swarm-python-api-template`.

The first target deployment profiles are:

```text
- Felix Media Redirector
- Felix Media Server
```

---

## 2. Current Gaps

The current repository is already strong as a deployment tool, but the implementation is still heavily API-shaped.

Current assumptions that block Nginx-only deployment include:

```text
- base compose always includes Redis.
- api.template.yml is always present.
- stack generation assumes an API service exists.
- validation assumes API-oriented modules and secrets.
- menu language still leans toward backend app terminology.
- health/log workflows assume API service naming.
```

Because of these assumptions, Nginx-only deployment should not be added as a workaround profile inside the existing API shape.

---

## 3. Target Design Principle

The repository should evolve from:

```text
backend app deployment repo
```

to:

```text
generic deployment-profile-driven swarm repo
```

This means the repo should understand different stack families, starting with:

```text
- api
- nginx
```

---

## 4. Deployment Profile Model Changes

### 4.1 Current Limitation

The current `site-configs/*.json` schema mainly describes backend app needs.

### 4.2 Target Direction

The schema should be broadened so a deployment profile can describe the kind of stack that should be built.

Recommended additional fields:

```text
- kind
- stack.family
- stack.role
- services.api
- services.redis
- services.database
- routing.defaultDomain
- health.strategy
```

Illustrative direction:

```text
kind: nginx
stack.family: nginx
stack.role: redirector | media-server
services.api: false
services.redis: false
services.database: false
```

This can be introduced as a schema evolution rather than a breaking rewrite.

---

## 5. Compose Builder Changes

### 5.1 Current Limitation

The compose builder always constructs an API-style stack:

```text
base.yml
+ api.template.yml
+ optional database module
+ footer.yml
```

### 5.2 Target Direction

The compose-module system should support multiple stack families.

Recommended direction:

```text
setup/compose-modules/
  api/
    ...
  nginx/
    base.yml
    nginx.template.yml
    footer.yml
    snippets/
      proxy-traefik-*.yml
      proxy-none.ports.yml
```

The build logic should first resolve the stack family from the selected deployment profile, then use the correct compose template family.

### 5.3 Nginx Family Expectations

The Nginx stack family should support:

```text
- single nginx service
- Traefik routing or direct-port mode
- configurable replicas
- memory limits
- optional bind-mounted data paths only where explicitly needed
- profile-specific image name and image version
```

For the Felix first phase, the Nginx deployment model should split responsibilities clearly:

```text
- redirector profile  -> stock nginx image + deployment-managed redirect config
- media-server profile  -> dedicated baked media-server image
```

---

## 6. Setup Wizard Changes

The setup wizard should remain the primary user entry point, but its wording and logic should broaden.

### 6.1 Terminology Updates

The wizard should prefer:

```text
- deployment profile
- stack family
- deployment kind
```

over backend-specific wording.

### 6.2 Dynamic Question Flow

The wizard should ask only the questions relevant to the chosen profile.

For Nginx-only profiles, it should skip:

```text
- database mode selection
- admin UI configuration
- backend-specific secret prompts
- API-specific environment setup
```

For Nginx-only profiles, it should still ask:

```text
- stack name
- domain
- proxy type
- SSL mode when relevant
- image name
- image version
- replica count
- memory limit
- data root when relevant
```

---

## 7. Menu and Operations Changes

The main menu should stay unified, but actions should adapt to the active profile.

### 7.1 Actions That Should Stay Generic

```text
- Re-run setup wizard
- Deploy to Swarm
- Rebuild stack
- Inspect artifacts
- Remove deployment
```

### 7.2 Actions That Should Become Conditional

```text
- API log shortcuts
- database log shortcuts
- database secret helpers
- admin UI toggles
```

For Nginx-only profiles, logs and health checks should resolve service names correctly and avoid API-specific assumptions.

---

## 8. Validation Changes

The validation script should be generalized so it validates the active stack family instead of assuming API infrastructure.

### 8.1 Nginx-Only Validation Expectations

Validation for Nginx-only profiles should confirm:

```text
- deployment profile exists
- nginx compose family files exist
- .env contains required generic deployment keys
- swarm-stack.yml exists or can be generated
- referenced image name and image version are present in config
- required secrets are present only when the profile declares them
```

### 8.2 Backward Compatibility Goal

API deployments must continue to validate successfully after the generalization.

---

## 9. Health, Logs, and Service Naming

The repo should stop assuming that the main runtime service is always `api`.

Recommended direction:

```text
- derive primary service name from stack family or profile metadata
- allow health strategy to be profile-specific
- use nginx-specific log shortcuts for nginx profiles
```

For the first Nginx phase, health can be lightweight:

```text
- service exists
- service tasks are running
- optional HTTP status check for the active domain
```

---

## 10. Secrets Strategy

Nginx-only deployments should not inherit API secret requirements by default.

### 10.1 Redirector

The Felix redirector should ideally require no custom Docker secrets in Phase 1 unless a later config approach introduces them.

It should use:

```text
- a stock nginx image
- deployment-managed redirect config files or generated config
- no dedicated redirector image build pipeline
```

### 10.2 Media Server

The Felix media-server should also default to no secrets if it only serves public baked media.

It should use:

```text
- a dedicated media-server image built in docker-nginx-webserver
```

### 10.3 Profile-Driven Rule

Secrets should be driven by profile metadata instead of assumed globally.

---

## 11. Initial Felix Profiles

The first Nginx deployment profiles should be explicit and separate.

Recommended profiles:

```text
- felix_media_redirector
- felix_media_server
```

Each profile should define:

```text
- display name
- stack family = nginx
- stack role
- default image name
- default image version
- default replica count
- domain expectations
- required env keys
- secrets list
```

The intended first-image mapping should be:

```text
- felix_media_redirector -> nginx:alpine (or equivalent stock nginx image)
- felix_media_server       -> dedicated Felix media-server image
```

---

## 12. Phased Rollout

### Phase 1. Generalize the Deployment Profile Model

Deliver:

```text
- extended profile schema
- profile metadata for stack family / kind / role
- helper functions that read the new fields
```

Acceptance criteria:

```text
- The repo can distinguish between API and Nginx profiles before stack build begins.
```

### Phase 2. Add Nginx Compose Family

Deliver:

```text
- setup/compose-modules/nginx/
- nginx service template
- nginx proxy snippets
- nginx footer template
```

Acceptance criteria:

```text
- The stack builder can generate a valid nginx-only swarm-stack.yml.
```

### Phase 3. Update Wizard and Menu Flow

Deliver:

```text
- profile-aware wizard branching
- profile-aware menu behavior
- conditional prompts and operations
```

Acceptance criteria:

```text
- Selecting a Felix nginx profile does not trigger irrelevant DB/API prompts.
```

### Phase 4. Generalize Validation, Health, and Logs

Deliver:

```text
- stack-family-aware validation
- stack-family-aware health checks
- stack-family-aware log helpers
```

Acceptance criteria:

```text
- nginx-only deployments can be validated and inspected without API assumptions.
```

### Phase 5. Add Felix Profiles and Verify End-to-End Flow

Deliver:

```text
- felix_media_redirector profile
- felix_media_server profile
- end-to-end setup, build-stack, deploy, and inspect verification
```

Acceptance criteria:

```text
- Both Felix nginx roles can be deployed through the standard quick-start and wizard flow.
- Existing API deployment behavior still works.
```

---

## 13. Migration and Compatibility Rules

To keep the rollout safe, the implementation should follow these rules:

```text
- Keep existing API profiles working during every phase.
- Add new schema fields in a backward-compatible way where possible.
- Avoid forcing nginx deployments through fake API/Redis/DB placeholders.
- Keep the root-level deployment model unchanged.
```

---

## 14. Success Criteria

This plan is successful when:

```text
- swarm-python-api-template can deploy nginx-only stacks cleanly.
- Felix redirector and media-server profiles work through the normal setup flow.
- Existing API deployments still function.
- The repo becomes a truly generic deployment-profile-driven swarm repo.
```
