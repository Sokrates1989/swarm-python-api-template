# Nginx-Only Deployment Overview

## 1. Purpose

This document defines how `swarm-python-api-template` should evolve to support Nginx-only Docker Swarm deployments in addition to API deployments.

The first target Nginx-only deployments are:

```text
- Felix redirector
- Felix media-server
```

The current decision is:

```text
Use swarm-python-api-template as the canonical deployment-profile-driven repo.
Broaden it from backend-oriented deployment profiles to generic deployment profiles.
Add support for nginx-only stacks without forcing them into API-shaped abstractions.
Keep local Nginx image authoring in docker-nginx-webserver.
Use a stock nginx image for the redirector with deployment-managed redirect config.
```

---

## 2. Related Documents

This plan is closely related to the Felix media architecture documents in the Nginx build repository:

```text
d:/Development/Code/nginx/docker-nginx-webserver/plan/media_delivery/
```

The local Nginx build-host planning documents live here:

```text
d:/Development/Code/nginx/docker-nginx-webserver/plan/multi-src-quick-start-maturement/
```

The detailed implementation plan for this repository is defined here:

- [Nginx-Only Deployment Enablement Plan](./nginx_only_deployment_enablement_plan_v1.md)

---

## 3. Why This Repo Should Own the Deployment Workflow

`swarm-python-api-template` already has the correct deployment operating model:

```text
- Deployment profiles in site-configs/.
- Root-level .env and swarm-stack.yml.
- Setup wizard.
- Secrets workflow.
- Rebuild/redeploy menu flow.
- Health and artifact inspection workflow.
```

This makes it the best place to add Nginx-only deployment profiles instead of maturing a second deployment repo from scratch.

---

## 4. Scope

This repo should become capable of deploying:

```text
- API-based stacks.
- Nginx-only redirector stacks based on a stock nginx image.
- Nginx-only media-server stacks based on a dedicated media-server image.
```

### 4.1 In Scope

```text
- Deployment profile schema extension.
- Setup wizard updates.
- Compose module system changes.
- Validation updates.
- Menu behavior for nginx-only profiles.
- Felix redirector and media-server deployment profiles.
```

### 4.2 Out of Scope

```text
- Building Nginx images locally.
- Managing media source content.
- Replacing docker-nginx-webserver as the Nginx image workspace.
- Refactoring unrelated backend application logic.
```

---

## 5. Target Mental Model

The target mental model should become:

```text
Select deployment profile
  ↓
Wizard loads profile metadata
  ↓
Repo builds the correct stack family
  ↓
Repo writes root .env and swarm-stack.yml
  ↓
Repo manages secrets, deploy, update, health, and logs
```

The important change is that `deployment profile` should no longer implicitly mean `backend API app`.

---

## 6. Target Outcome

After this plan is implemented, the repo should be able to:

```text
- Deploy a Felix redirector stack from a dedicated deployment profile using a stock nginx image.
- Deploy a Felix media-server stack from a dedicated deployment profile.
- Keep API deployments working.
- Reuse the existing menu-driven deployment UX.
```

---

## 7. Summary

`swarm-python-api-template` should become the canonical deployment repository for both API and Nginx-only deployments.

It should do this by generalizing its deployment-profile model, not by forcing Nginx stacks into the existing API-only assumptions. The redirector should be deployed with a stock nginx image and deployment-managed config, while the media-server should consume the dedicated media-server image.
