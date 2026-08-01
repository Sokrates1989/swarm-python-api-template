# Secure Messaging Internal API Deployment Plan

## 1. Purpose

This document defines the Swarm deployment-side implementation plan for adding an internal-only API deployment style to `swarm-python-api-template`.

The first target use case is the `secure_messaging` API app from `python-api-template`.

The deployment repository should become capable of deploying a service that is:

```text
- an API image
- reachable only on an internal Docker overlay network
- not routed by Traefik
- not exposed through published ports
- configured through Docker Swarm secrets
- callable by other services as http://secure_messaging_api:8080
```

This is a deployment-template extension. It should not create a new standalone `swarm-secure-messaging` repository.

---

## 2. Current Repository Findings

The repository already uses deployment profiles in:

```text
site-configs/*.json
```

The setup wizard loads those profiles and writes root deployment artifacts:

```text
.env
swarm-stack.yml
```

The stack builder currently supports multiple stack families, including:

```text
- api
- nginx
```

Existing API generation is still public-API-shaped:

```text
setup/compose-modules/base.yml
setup/compose-modules/api.template.yml
setup/compose-modules/<database>-local.yml
setup/compose-modules/footer.yml
```

Important current assumptions:

```text
- API stacks usually include Redis.
- API stacks usually include standard admin/backup secrets.
- API stacks usually use Traefik labels or direct published ports.
- The setup wizard requires a public domain for API-style profiles.
- Validation expects API-style required keys and standard secrets.
- Health and log helpers assume the primary service is named api.
```

Secure messaging needs a new API deployment style, not a workaround using `PROXY_TYPE=none`, because `PROXY_TYPE=none` currently means direct public port publication.

---

## 3. Target Deployment Architecture

Target production shape:

```text
Other Swarm services
  -> secure_messaging_internal overlay network
  -> http://secure_messaging_api:8080/v1/notify
  -> Authorization: Bearer <client-specific-token>
  -> secure_messaging_api sends Telegram/email
```

Deployment service:

```text
secure_messaging_api
```

Internal network:

```text
secure_messaging_internal
```

Internal URL:

```text
http://secure_messaging_api:8080
```

The generated stack must not contain:

```text
- ports:
- traefik.enable=true
- traefik.http.routers.*
- public domain routing
- public Traefik network attachment
```

The deployment still requires application-level bearer authentication because network isolation is not enough on its own.

---

## 4. Deployment Profile Model Changes

Add a secure messaging deployment profile:

```text
site-configs/secure_messaging.json
```

Recommended profile model:

```json
{
  "$schema": "site-config-schema",
  "version": "3.1",
  "appId": "secure_messaging",
  "name": "Secure Messaging",
  "description": "Internal-only notification API for Swarm services",
  "kind": "api",
  "stack": {
    "family": "api",
    "role": "internal-api",
    "primaryService": "secure_messaging_api"
  },
  "exposure": {
    "type": "internal",
    "publicDomainRequired": false,
    "traefik": false,
    "publishedPorts": false
  },
  "routing": {
    "containerPort": 8080,
    "internalServiceName": "secure_messaging_api",
    "internalUrl": "http://secure_messaging_api:8080"
  },
  "networking": {
    "internalNetwork": "secure_messaging_internal",
    "externalNetwork": true,
    "attachable": true
  },
  "database": {
    "type": "none",
    "defaultMode": "none"
  },
  "services": {
    "api": true,
    "redis": false,
    "database": false
  },
  "image": {
    "name": "sokrates1989/python-api-secure-messaging",
    "defaultVersion": "latest"
  },
  "resources": {
    "defaultReplicas": 1,
    "defaultMemoryLimit": "unlimited"
  },
  "secrets": [
    "secure_messaging_allowed_client_tokens",
    "secure_messaging_telegram_bot_token",
    "secure_messaging_telegram_chat_id",
    "secure_messaging_smtp_host",
    "secure_messaging_smtp_port",
    "secure_messaging_smtp_username",
    "secure_messaging_smtp_password",
    "secure_messaging_smtp_use_tls",
    "secure_messaging_email_from",
    "secure_messaging_email_to_default"
  ],
  "envKeys": [
    "APP_PROFILE",
    "BACKEND_APP_ID",
    "DB_TYPE",
    "PORT",
    "SECURE_MESSAGING_ALLOWED_CLIENT_TOKENS_FILE",
    "SECURE_MESSAGING_TELEGRAM_ENABLED",
    "SECURE_MESSAGING_EMAIL_ENABLED"
  ],
  "notes": "Internal-only API. No public domain, Traefik labels, or published ports."
}
```

The exact Docker image name can be changed later, but the profile should be explicit and not inherit public API defaults.

---

## 5. Files To Add

Add:

```text
site-configs/secure_messaging.json
setup/compose-modules/secure-messaging-api.template.yml
setup/compose-modules/secure-messaging-footer.yml
setup/templates/secrets.secure-messaging.env.template
docs/SECURE_MESSAGING.md
testing/examples/swarm-stack-secure-messaging-internal.yml
```

The testing example is optional but recommended because internal-only stacks are easy to accidentally expose during future edits.

---

## 6. Files To Change

Change:

```text
setup/modules/site_helpers.sh
setup/setup-wizard.sh
setup/modules/config-builder.sh
setup/modules/secret-manager.sh
setup/modules/secrets_template_sync.sh
setup/modules/menu_handlers.sh
setup/modules/health-check.sh
scripts/build-site-stack.sh
scripts/validate-site.sh
README.md
site-configs/README.md
setup/compose-modules/README.md
```

The changes should be profile-aware and backward-compatible with existing API and nginx profiles.

---

## 7. Compose Template Plan

Create:

```text
setup/compose-modules/secure-messaging-api.template.yml
```

Target service template:

```yaml
# Secure Messaging internal API service template.
# This service is intentionally internal-only.
services:
  secure_messaging_api:
    image: ${IMAGE_NAME}:${IMAGE_VERSION}
    networks:
      secure_messaging_internal:
        aliases:
          - secure_messaging_api
    secrets:
      - secure_messaging_allowed_client_tokens
      - secure_messaging_telegram_bot_token
      - secure_messaging_telegram_chat_id
      - secure_messaging_smtp_host
      - secure_messaging_smtp_port
      - secure_messaging_smtp_username
      - secure_messaging_smtp_password
      - secure_messaging_smtp_use_tls
      - secure_messaging_email_from
      - secure_messaging_email_to_default
    environment:
      APP_PROFILE: secure_messaging
      BACKEND_APP_ID: secure_messaging
      DB_TYPE: none
      DB_MODE: none
      PORT: 8080
      DEBUG: ${DEBUG:-false}
      SECURE_MESSAGING_ALLOWED_CLIENT_TOKENS_FILE: /run/secrets/secure_messaging_allowed_client_tokens
      SECURE_MESSAGING_TELEGRAM_ENABLED: ${SECURE_MESSAGING_TELEGRAM_ENABLED:-true}
      SECURE_MESSAGING_TELEGRAM_BOT_TOKEN_FILE: /run/secrets/secure_messaging_telegram_bot_token
      SECURE_MESSAGING_TELEGRAM_CHAT_ID_FILE: /run/secrets/secure_messaging_telegram_chat_id
      SECURE_MESSAGING_EMAIL_ENABLED: ${SECURE_MESSAGING_EMAIL_ENABLED:-true}
      SECURE_MESSAGING_SMTP_HOST_FILE: /run/secrets/secure_messaging_smtp_host
      SECURE_MESSAGING_SMTP_PORT_FILE: /run/secrets/secure_messaging_smtp_port
      SECURE_MESSAGING_SMTP_USERNAME_FILE: /run/secrets/secure_messaging_smtp_username
      SECURE_MESSAGING_SMTP_PASSWORD_FILE: /run/secrets/secure_messaging_smtp_password
      SECURE_MESSAGING_SMTP_USE_TLS_FILE: /run/secrets/secure_messaging_smtp_use_tls
      SECURE_MESSAGING_EMAIL_FROM_FILE: /run/secrets/secure_messaging_email_from
      SECURE_MESSAGING_EMAIL_TO_DEFAULT_FILE: /run/secrets/secure_messaging_email_to_default
      SECURE_MESSAGING_RATE_LIMIT_PER_MINUTE: ${SECURE_MESSAGING_RATE_LIMIT_PER_MINUTE:-30}
    deploy:
      mode: replicated
      replicas: ${API_REPLICAS:-1}
      update_config:
        parallelism: 1
        delay: 10s
        order: start-first
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health').read()"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 10s
```

Important:

```text
- No ports section.
- No deploy.labels Traefik section.
- No public network.
- No standard API admin/backup secrets unless intentionally added later.
```

Create:

```text
setup/compose-modules/secure-messaging-footer.yml
```

Target footer:

```yaml
networks:
  secure_messaging_internal:
    external: true

secrets:
  secure_messaging_allowed_client_tokens:
    external: true
  secure_messaging_telegram_bot_token:
    external: true
  secure_messaging_telegram_chat_id:
    external: true
  secure_messaging_smtp_host:
    external: true
  secure_messaging_smtp_port:
    external: true
  secure_messaging_smtp_username:
    external: true
  secure_messaging_smtp_password:
    external: true
  secure_messaging_smtp_use_tls:
    external: true
  secure_messaging_email_from:
    external: true
  secure_messaging_email_to_default:
    external: true
```

Use exact lowercase secret names for this central internal service. These names are intentionally not stack-prefixed because consuming services and operational docs can refer to one stable central service.

---

## 8. Stack Builder Plan

Change:

```text
setup/modules/config-builder.sh
```

Add a branch before the standard API builder:

```text
if STACK_ROLE=internal-api and APP_ID=secure_messaging:
  build_secure_messaging_stack_file
```

Recommended function:

```text
build_secure_messaging_stack_file(project_root)
```

It should:

```text
1. Write generated header.
2. Append secure-messaging-api.template.yml.
3. Append secure-messaging-footer.yml.
4. Do not append base.yml.
5. Do not append redis service.
6. Do not append database service.
7. Do not inject proxy snippets.
8. Do not call update_stack_secrets for standard API secrets.
```

The builder should keep existing behavior for:

```text
- public API profiles
- nginx profiles
```

---

## 9. Setup Wizard Plan

Change:

```text
setup/setup-wizard.sh
```

For profiles where:

```text
exposure.type=internal
```

the wizard should skip:

```text
- public domain prompt
- proxy type prompt
- SSL mode prompt
- Traefik network prompt
- database mode prompt
- admin UI prompt
- public direct port prompt
```

The wizard should still ask:

```text
- stack name
- image name
- image version
- replica count
- memory limit
- whether providers should default enabled
- data root only if the profile needs data mounts
```

Generated `.env` for secure messaging should include:

```text
STACK_NAME=secure-messaging
DEPLOYMENT_PROFILE_ID=secure_messaging
BACKEND_APP_ID=secure_messaging
APP_PROFILE=secure_messaging
STACK_FAMILY=api
STACK_ROLE=internal-api
PRIMARY_SERVICE=secure_messaging_api
DB_TYPE=none
DB_MODE=none
PROXY_TYPE=internal
PORT=8080
IMAGE_NAME=sokrates1989/python-api-secure-messaging
IMAGE_VERSION=<selected>
API_REPLICAS=1
SECURE_MESSAGING_INTERNAL_NETWORK=secure_messaging_internal
SECURE_MESSAGING_API_URL=http://secure_messaging_api:8080
SECURE_MESSAGING_TELEGRAM_ENABLED=true
SECURE_MESSAGING_EMAIL_ENABLED=true
SECURE_MESSAGING_RATE_LIMIT_PER_MINUTE=30
```

No `DOMAIN` should be required for internal profiles. If the code path still requires `DOMAIN` for old assumptions, set it to an empty value and ensure validation accepts that for internal profiles.

---

## 10. Secret Management Plan

Create:

```text
setup/templates/secrets.secure-messaging.env.template
```

Template:

```text
# Secure Messaging Docker Secrets Template
# Delete this file after creating Docker secrets.

secure_messaging_allowed_client_tokens=
secure_messaging_telegram_bot_token=
secure_messaging_telegram_chat_id=
secure_messaging_smtp_host=
secure_messaging_smtp_port=
secure_messaging_smtp_username=
secure_messaging_smtp_password=
secure_messaging_smtp_use_tls=
secure_messaging_email_from=
secure_messaging_email_to_default=
```

Allowed token example value:

```json
{"wikijs-backup":"replace-with-long-random-token"}
```

Change:

```text
setup/modules/secret-manager.sh
```

Add profile-driven secret creation:

```text
- For standard API profiles, keep current prefixed standard secrets.
- For secure_messaging, create exact external secret names from the secure template.
```

Do not force secure messaging through:

```text
DB_PASSWORD
ADMIN_API_KEY
BACKUP_RESTORE_API_KEY
BACKUP_DELETE_API_KEY
DB_UI_ADMIN_PASSWORD
```

These secrets are unrelated.

---

## 11. Internal Network Plan

The secure messaging service should use:

```text
secure_messaging_internal
```

Because the network is external, Swarm will not create it automatically from the stack file.

Add a helper or documentation command:

```bash
docker network create \
  --driver overlay \
  --attachable \
  secure_messaging_internal
```

Validation should check:

```text
- network exists
- network driver is overlay
- network is attachable where possible
```

Consuming services must attach to the same network.

Recommended consuming service snippet:

```yaml
services:
  wikijs_backup:
    networks:
      - secure_messaging_internal
    secrets:
      - secure_messaging_client_token_wikijs_backup
    environment:
      SECURE_MESSAGING_API_URL: http://secure_messaging_api:8080
      SECURE_MESSAGING_CLIENT_TOKEN_FILE: /run/secrets/secure_messaging_client_token_wikijs_backup

networks:
  secure_messaging_internal:
    external: true

secrets:
  secure_messaging_client_token_wikijs_backup:
    external: true
```

---

## 12. Validation Plan

Change:

```text
scripts/validate-site.sh
```

For secure messaging profiles, validate:

```text
- .env exists.
- DEPLOYMENT_PROFILE_ID=secure_messaging.
- STACK_ROLE=internal-api.
- PRIMARY_SERVICE=secure_messaging_api.
- DB_TYPE=none.
- DB_MODE=none.
- PROXY_TYPE=internal.
- PORT=8080.
- swarm-stack.yml exists.
- secure_messaging_api service exists in generated stack.
- secure_messaging_internal network is external.
- no "ports:" key exists under secure_messaging_api.
- no "traefik.enable=true" exists anywhere in generated stack.
- all secure messaging Docker secrets exist.
- secure_messaging_internal Docker network exists.
```

Validation should fail hard if generated stack contains public exposure:

```text
- traefik.enable=true
- traefik.http.routers
- published:
- ports:
```

For old public API and nginx profiles, keep current validation behavior.

---

## 13. Health And Logs Plan

Change:

```text
setup/modules/health-check.sh
setup/modules/menu_handlers.sh
```

The primary service should come from:

```text
PRIMARY_SERVICE
```

For secure messaging:

```text
PRIMARY_SERVICE=secure_messaging_api
```

Health checks should:

```text
- wait for secure_messaging_api desired replicas.
- inspect service tasks.
- show recent secure_messaging_api logs.
- run an internal health probe where possible.
```

Because the service is not public, do not try:

```text
curl https://<domain>/health
```

Instead, document internal checks:

```bash
docker service logs <stack>_secure_messaging_api --tail 50
docker service ps <stack>_secure_messaging_api --no-trunc
```

Optional internal probe through a temporary container:

```bash
docker run --rm --network secure_messaging_internal curlimages/curl:latest \
  curl -s http://secure_messaging_api:8080/health
```

---

## 14. Generated Stack Acceptance Example

The generated `swarm-stack.yml` for secure messaging should look structurally like:

```yaml
services:
  secure_messaging_api:
    image: ${IMAGE_NAME}:${IMAGE_VERSION}
    networks:
      secure_messaging_internal:
        aliases:
          - secure_messaging_api
    secrets:
      - secure_messaging_allowed_client_tokens
      - secure_messaging_telegram_bot_token
      - secure_messaging_telegram_chat_id
      - secure_messaging_smtp_host
      - secure_messaging_smtp_port
      - secure_messaging_smtp_username
      - secure_messaging_smtp_password
      - secure_messaging_smtp_use_tls
      - secure_messaging_email_from
      - secure_messaging_email_to_default
    environment:
      APP_PROFILE: secure_messaging
      BACKEND_APP_ID: secure_messaging
      DB_TYPE: none
      DB_MODE: none
      PORT: 8080
      SECURE_MESSAGING_ALLOWED_CLIENT_TOKENS_FILE: /run/secrets/secure_messaging_allowed_client_tokens
    deploy:
      replicas: ${API_REPLICAS:-1}

networks:
  secure_messaging_internal:
    external: true

secrets:
  secure_messaging_allowed_client_tokens:
    external: true
```

It must not contain:

```text
traefik
published:
ports:
```

---

## 15. Consuming Service Integration Plan

Every consuming service should receive only:

```text
SECURE_MESSAGING_API_URL=http://secure_messaging_api:8080
SECURE_MESSAGING_CLIENT_TOKEN_FILE=/run/secrets/<service-specific-token-secret>
secure_messaging_internal network attachment
```

Example request:

```bash
TOKEN="$(cat /run/secrets/secure_messaging_client_token_wikijs_backup)"

curl -X POST "$SECURE_MESSAGING_API_URL/v1/notify" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "app": "wikijs-backup",
    "level": "success",
    "title": "Wiki.js backup completed",
    "message": "The backup finished successfully.",
    "tags": ["backup", "wikijs"],
    "provider": "all"
  }'
```

Provider credentials must never be mounted into consuming services.

---

## 16. Documentation Plan

Create:

```text
docs/SECURE_MESSAGING.md
```

Include:

```text
- purpose
- internal-only security model
- no public route warning
- network creation command
- Docker secret creation workflow
- setup wizard workflow
- generated .env example
- generated stack expectations
- consuming service compose snippet
- consuming service curl example
- validation checklist
- troubleshooting
```

Update:

```text
README.md
site-configs/README.md
setup/compose-modules/README.md
```

Document the new profile concept:

```text
exposure.type=internal
stack.role=internal-api
```

---

## 17. Phased Implementation

### Phase 1. Profile Schema And Metadata

Deliver:

```text
- site-configs/secure_messaging.json.
- site_helpers.sh reads exposure and internal networking fields.
- .env generation understands internal profile defaults.
```

Acceptance criteria:

```text
- setup wizard can identify secure_messaging as an internal API profile.
- internal profile metadata is visible in the setup flow.
```

### Phase 2. Internal Compose Family

Deliver:

```text
- secure-messaging-api.template.yml.
- secure-messaging-footer.yml.
- config-builder branch for internal-api.
- build-site-stack.sh support for secure_messaging.
```

Acceptance criteria:

```text
- Generated stack contains secure_messaging_api.
- Generated stack contains secure_messaging_internal.
- Generated stack has no ports and no Traefik labels.
```

### Phase 3. Setup Wizard And Secrets

Deliver:

```text
- internal profile skips public domain/proxy prompts.
- secure messaging .env keys are written.
- secure messaging secrets template is added.
- secret manager can create exact secure messaging secrets.
```

Acceptance criteria:

```text
- Wizard can configure secure messaging without asking for a public domain.
- Secret workflow creates only secure messaging secrets.
```

### Phase 4. Validation, Health, And Menu Support

Deliver:

```text
- validate-site.sh internal-only checks.
- health check uses PRIMARY_SERVICE.
- logs menu uses PRIMARY_SERVICE.
- no public URL health probe for internal profiles.
```

Acceptance criteria:

```text
- Validation fails if public exposure appears.
- Health/log menu targets <stack>_secure_messaging_api.
```

### Phase 5. End-To-End Deployment Verification

Deliver:

```text
- docs/SECURE_MESSAGING.md.
- testing example stack.
- full setup, build, validate, deploy, internal curl test documented.
```

Acceptance criteria:

```text
- A consuming service on secure_messaging_internal can call http://secure_messaging_api:8080/v1/notify.
- A service not on that network cannot reach it.
- Public internet has no route to /v1/notify.
```

---

## 18. Security Acceptance Criteria

The Swarm deployment work is complete when:

```text
- secure_messaging_api has no published public ports.
- secure_messaging_api has no Traefik labels.
- secure_messaging_api is not attached to a public Traefik network.
- secure_messaging_api is attached only to secure_messaging_internal.
- secure_messaging_internal is an external overlay network.
- provider credentials are mounted only into secure_messaging_api.
- consuming services receive only their own client token secret.
- generated validation fails on accidental public exposure.
- default replica count is 1 for in-memory rate-limit correctness.
```

---

## 19. Deployment Commands

Create internal overlay network:

```bash
docker network create \
  --driver overlay \
  --attachable \
  secure_messaging_internal
```

Create provider and token secrets through the planned secret workflow, or manually:

```bash
printf '%s' '{"wikijs-backup":"replace-with-token"}' \
  | docker secret create secure_messaging_allowed_client_tokens -
```

Build stack:

```bash
./scripts/build-site-stack.sh
```

Validate:

```bash
./scripts/validate-site.sh
```

Deploy:

```bash
set -a
source .env
set +a
docker stack deploy -c <(docker compose -f swarm-stack.yml config) "$STACK_NAME"
```

Internal health smoke test:

```bash
docker run --rm --network secure_messaging_internal curlimages/curl:latest \
  curl -s http://secure_messaging_api:8080/health
```

Internal notify smoke test:

```bash
docker run --rm --network secure_messaging_internal curlimages/curl:latest \
  sh -c 'curl -s -X POST http://secure_messaging_api:8080/v1/notify \
    -H "Authorization: Bearer replace-with-token" \
    -H "Content-Type: application/json" \
    -d "{\"app\":\"wikijs-backup\",\"level\":\"info\",\"title\":\"Smoke test\",\"message\":\"Secure messaging internal smoke test.\",\"tags\":[\"smoke\"],\"provider\":\"all\"}"'
```

---

## 20. Rollback Strategy

Rollback is image-tag based:

```bash
docker service update \
  --image sokrates1989/python-api-secure-messaging:<previous-version> \
  <stack>_secure_messaging_api
```

Configuration rollback:

```text
- Restore previous .env.
- Restore previous swarm-stack.yml if needed.
- Re-run docker stack deploy.
```

Secret rollback:

```text
- Docker secrets cannot be updated in place while attached.
- Stop/remove stack before recreating provider secrets.
- Recreate exact secret names.
- Redeploy stack.
```

---

## 21. Future Enhancements

Possible later enhancements:

```text
- Generic internal-api stack role for more internal services.
- Profile-driven arbitrary secret lists.
- Profile-driven arbitrary env-to-secret-file mappings.
- Automatic external overlay network creation helper.
- Internal-only smoke-test helper in quick-start menu.
- Multi-replica support with Redis-backed rate limiting.
- Optional private Traefik entrypoint for VPN-only access.
```

Do not add public routing as part of the secure messaging v1.

---

## 22. Implementation Prompt For Codex

```text
Extend swarm-python-api-template to support an internal-only API deployment style for secure_messaging.

Do not create a new deployment repository.
Do not expose the service publicly.
Do not add Traefik labels.
Do not publish ports.

Add a deployment profile:
site-configs/secure_messaging.json

Add an internal API stack role:
STACK_FAMILY=api
STACK_ROLE=internal-api
PRIMARY_SERVICE=secure_messaging_api
PROXY_TYPE=internal
DB_TYPE=none
DB_MODE=none

Add compose templates that generate:
- service secure_messaging_api
- external network secure_messaging_internal
- no public ports
- no Traefik labels
- exact Docker secrets for secure messaging provider credentials

Update setup wizard:
- skip public domain, proxy, SSL, DB, and admin UI prompts for internal profiles.
- write secure messaging .env keys.

Update secret manager:
- create secure messaging secrets from a dedicated template.
- do not require standard API database/admin/backup secrets.

Update validation:
- fail if generated stack contains Traefik labels or ports.
- check secure messaging secrets and internal network.

Update health/log menu:
- use PRIMARY_SERVICE.
- avoid public health probes for internal-only profiles.

Keep existing public API and nginx deployments working.
```
