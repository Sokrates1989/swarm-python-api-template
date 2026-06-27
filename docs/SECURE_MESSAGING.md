# Secure Messaging Deployment

Internal-only notification API deployment for Docker Swarm.

## Overview

The secure messaging deployment provides an internal API that other Swarm services can call to send notifications via Telegram and email.

**Security Model:**
- Internal-only (no public exposure)
- Bearer token authentication per calling service
- Docker overlay network isolation
- Provider credentials only mounted into secure messaging service

## Prerequisites

1. Docker Swarm initialized
2. Internal overlay network created

## Setup

### 1. Create Internal Network

```bash
docker network create \
  --driver overlay \
  --attachable \
  secure_messaging_internal
```

### 2. Run Setup Wizard

```bash
./quick-start.sh
```

Select the `secure_messaging` deployment profile. The wizard will:
- Skip public domain/proxy prompts (internal-only)
- Ask for stack name and image version
- Configure provider enablement
- Generate `.env` and `swarm-stack.yml`

### 3. Create Docker Secrets

Create the secrets template:

```bash
cp setup/templates/secrets.secure-messaging.env.template secrets.env
# Edit secrets.env with your values
```

Create secrets (run on Swarm manager):

```bash
# Auth token (single shared secret)
printf '%s' 'replace-with-long-random-token' | \
  docker secret create secure_messaging_auth_token -

# Telegram metadata (JSON - recipient keys to chat_ids)
printf '%s' '{"backup":{"info":"-5109048777","warning":"-5139430766","error":"-4994923325"}}' | \
  docker secret create secure_messaging_telegram_metadata -

# Telegram tokens (JSON - bot tokens)
printf '%s' '{"bot-main":"bot-token-1","bot-alerts":"bot-token-2"}' | \
  docker secret create secure_messaging_telegram_tokens -

# Email metadata (JSON - host, port, username, and nested receivers)
printf '%s' '{"gmail-primary":{"host":"smtp.gmail.com","port":"587","username":"primary@gmail.com","use_tls":"true","from":"primary@gmail.com","receivers":{"info":"info@example.com","warning":"alerts@example.com","error":"oncall@example.com"}}}' | \
  docker secret create secure_messaging_email_metadata -

# Email passwords (JSON - SMTP passwords)
printf '%s' '{"gmail-primary":"app-password-1","strato-backup":"app-password-2"}' | \
  docker secret create secure_messaging_email_passwords -
```

**Security Note:** Never commit secrets to git. The template file should be deleted after use.

### 4. Build and Deploy

```bash
# Build stack
./scripts/build-site-stack.sh

# Validate
./scripts/validate-site.sh

# Deploy
set -a
source .env
set +a
docker stack deploy -c <(docker compose -f swarm-stack.yml config) "$STACK_NAME"
```

## Verification

### Check Service Status

```bash
docker service ps ${STACK_NAME}_secure_messaging_api --no-trunc
docker service logs ${STACK_NAME}_secure_messaging_api --tail 50
```

### Internal Health Check

```bash
docker run --rm --network secure_messaging_internal curlimages/curl:latest \
  curl -s http://secure_messaging_api:8080/health
```

Expected response:
```json
{
  "status": "OK",
  "app_profile": "secure_messaging",
  "backend_app": "Secure Messaging",
  "database_type": "none",
  "startup_probe_status": "skipped"
}
```

### Test Notification

```bash
docker run --rm --network secure_messaging_internal curlimages/curl:latest \
  sh -c 'curl -s -X POST http://secure_messaging_api:8080/v1/notify \
    -H "Authorization: Bearer your-client-token" \
    -H "Content-Type: application/json" \
    -d "{\"app\":\"wikijs-backup\",\"title\":\"Smoke test\",\"message\":\"Secure messaging internal smoke test.\",\"sender\":\"backup\",\"to\":\"info\",\"provider\":\"all\"}"'
```

## Authentication

### Per-Client Token Registry (Recommended)

Each consuming service should have its own bearer token stored independently.
Create a JSON map and provision it as a Docker secret:

```bash
# Create client-token registry JSON
printf '%s' '{"file-backup":"token-abc123","wiki-backup":"token-xyz789"}' | \
  docker secret create secure_messaging_client_tokens -
```

Point the API service at the registry file by setting:

```
SECURE_MESSAGING_CLIENT_TOKENS_FILE=/run/secrets/secure_messaging_client_tokens
```

When the registry is configured, each client authenticates with its own token.
A warning is logged if the legacy single-token fallback is used, which aids migration
tracking.

### Legacy Single-Token Mode (Backward Compatible Fallback)

When `SECURE_MESSAGING_CLIENT_TOKENS_FILE` is not set, the API falls back to the
original single shared token (`SECURE_MESSAGING_AUTH_TOKEN`). This mode still works
for all existing deployments but all callers share one token, which means one
compromised client affects every other caller.

Migrate by provisioning the client token registry and setting `SECURE_MESSAGING_CLIENT_TOKENS_FILE`.

## Consuming Service Integration

### Pattern 1: Swarm Service (Overlay Network — Recommended)

Services running inside the Swarm attach to `secure_messaging_internal` and mount
their own client token secret:

```yaml
services:
  wikijs_backup:
    image: wikijs/backup:latest
    networks:
      - secure_messaging_internal
      - default
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

From within the service:

```bash
TOKEN="$(cat /run/secrets/secure_messaging_client_token_wikijs_backup)"

curl -X POST "$SECURE_MESSAGING_API_URL/v1/notify" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"app\": \"wikijs-backup\",
    \"title\": \"Wiki.js backup completed\",
    \"message\": \"Backup finished at $(date).\",
    \"sender\": \"backup\",
    \"to\": \"info\",
    \"provider\": \"all\"
  }"
```

### Pattern 2: Host CLI Tool via Docker Host-Bridge (Recommended for Host Tools)

CLI tools running on the Swarm manager host (e.g. `file-backup`) cannot join the
overlay network directly. They can however launch a short-lived helper container that
runs on the network and exits immediately.

**Token storage on the host:**

```bash
# Create a root-owned token file (never readable by other users)
sudo sh -c 'printf "%s" "token-abc123" > /etc/file-backup/secure-messaging-token'
sudo chmod 0600 /etc/file-backup/secure-messaging-token
```

**Sending a notification from the host:**

```bash
TOKEN_FILE=/etc/file-backup/secure-messaging-token

docker run --rm \
  --network secure_messaging_internal \
  --volume "${TOKEN_FILE}:/tmp/sm-token:ro" \
  curlimages/curl:latest \
  sh -c '
    TOKEN="$(cat /tmp/sm-token)"
    curl -s --max-time 15 -X POST http://secure_messaging_api:8080/v1/notify \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"app\":\"file-backup\",\"title\":\"Backup succeeded\",\"message\":\"Backup complete.\",\"provider\":\"all\",\"to\":\"info\"}"
  '
```

The token file is bind-mounted read-only and its value never appears in `docker run`
arguments or the process list.

**file-backup integration:** `file-backup` implements this pattern automatically.
Configure it in `/etc/file-backup/file-backup.env`:

```bash
FILE_BACKUP_NOTIFY_ENABLED=true
FILE_BACKUP_NOTIFY_MODE=docker-bridge
FILE_BACKUP_NOTIFY_API_URL=http://secure_messaging_api:8080
FILE_BACKUP_NOTIFY_DOCKER_NETWORK=secure_messaging_internal
FILE_BACKUP_NOTIFY_TOKEN_FILE=/etc/file-backup/secure-messaging-token
```

Verify the configuration with:

```bash
file-backup notify-test
```

### Pattern 3: Host CLI Tool via Direct HTTP (Explicit Opt-In Only)

When the Docker host-bridge pattern is impractical, the same `secure_messaging`
profile can be deployed with a reachable host port instead of internal-only. This
is **not** a separate deployment profile — it is the standard exposure choice
offered by the setup wizard:

- Run the setup wizard and select the **Secure Messaging** profile.
- At the **Proxy type** prompt choose either:
  - `1) Traefik` to place the API behind your reverse proxy with TLS, or
  - `2) None (direct port)` to publish a host port directly.

**Security requirements for this mode:**

- Prefer binding the published port to `127.0.0.1` only; never expose `0.0.0.0`
  without a TLS-terminating reverse proxy in front.
- Use a dedicated per-client token. Do not share the token with Swarm services.
- Prefer Pattern 2 (Docker host-bridge) unless there is a specific reason not to.

Configure `file-backup` for direct HTTP (adjust the URL to match the published
port or Traefik domain you chose in the wizard):

```bash
FILE_BACKUP_NOTIFY_ENABLED=true
FILE_BACKUP_NOTIFY_MODE=direct-http
FILE_BACKUP_NOTIFY_API_URL=http://127.0.0.1:8095
FILE_BACKUP_NOTIFY_TOKEN_FILE=/etc/file-backup/secure-messaging-token
```

### Recipient Addressing

The `to` field accepts either a named key from the sender's receiver configuration
or a direct address:

- Named key: `"to": "info"` → looks up the `info` key in the sender's receivers map.
- Direct Telegram chat ID: `"to": "-1001234567890"` → sends directly to that chat.
- Direct email address: `"to": "ops@example.com"` → sends directly to that address.
- Comma-separated list: `"to": "info,ops@example.com"` → sends to both.

Named targets are optional convenience. A sender with valid credentials but no
pre-configured receivers is fully functional when callers supply `to` directly.

## Generated Stack Structure

The `swarm-stack.yml` contains:

```yaml
services:
  secure_messaging_api:
    image: sokrates1989/python-api-secure-messaging:latest
    networks:
      secure_messaging_internal:
        aliases:
          - secure_messaging_api
    secrets:
      - secure_messaging_auth_token
      - secure_messaging_telegram_metadata
      - secure_messaging_telegram_tokens
      - secure_messaging_email_metadata
      - secure_messaging_email_passwords
    environment:
      APP_PROFILE: secure_messaging
      # ... other env vars pointing to secrets files
      BACKEND_APP_ID: secure_messaging
      DB_TYPE: none
      # ... other env vars
    deploy:
      replicas: 1

networks:
  secure_messaging_internal:
    external: true

secrets:
  secure_messaging_auth_token:
    external: true
  secure_messaging_telegram_senders:
    external: true
  secure_messaging_email_senders:
    external: true
```

**Important:** The generated stack intentionally has:
- No `ports:` section
- No Traefik labels
- No public network attachment

## Rollback

### Image Rollback

```bash
docker service update \
  --image sokrates1989/python-api-secure-messaging:<previous-version> \
  ${STACK_NAME}_secure_messaging_api
```

### Configuration Rollback

1. Restore previous `.env`
2. Re-run `docker stack deploy`

### Secret Update

Docker secrets cannot be updated in place:

```bash
# Stop stack
docker stack rm ${STACK_NAME}

# Wait for full removal
sleep 10

# Remove and recreate secrets (example: updating auth token)
docker secret rm secure_messaging_auth_token
printf '%s' 'new-secret-token' | docker secret create secure_messaging_auth_token -

# Or update telegram tokens only (no full redeploy needed for token rotation)
docker service update --secret-rm secure_messaging_telegram_tokens ${STACK_NAME}_secure_messaging_api
printf '%s' '{"bot-main":"new-token-1","bot-alerts":"new-token-2"}' | docker secret create secure_messaging_telegram_tokens_v2 -
docker service update --secret-add src=secure_messaging_telegram_tokens_v2,target=secure_messaging_telegram_tokens ${STACK_NAME}_secure_messaging_api

# Redeploy
docker stack deploy -c swarm-stack.yml ${STACK_NAME}
```

## Validation

The `validate-site.sh` script checks:

- `.env` exists with correct `DEPLOYMENT_PROFILE_ID=secure_messaging`
- `STACK_ROLE=internal-api` and `PRIMARY_SERVICE=secure_messaging_api`
- No public ports in generated stack
- No Traefik labels in generated stack
- External `secure_messaging_internal` network
- All required secrets exist

## Troubleshooting

### Service Won't Start

Check logs:
```bash
docker service logs ${STACK_NAME}_secure_messaging_api --tail 100
```

Common issues:
- Missing required secrets
- Invalid JSON in sender configuration secrets
- Network `secure_messaging_internal` doesn't exist

### Can't Reach API from Other Services

1. Verify both services are on `secure_messaging_internal` network:
   ```bash
   docker network inspect secure_messaging_internal
   ```

2. Check service has correct token secret mounted

3. Verify DNS resolution works:
   ```bash
   docker run --rm --network secure_messaging_internal \
     curlimages/curl:latest curl -s http://secure_messaging_api:8080/health
   ```

### Notifications Not Sending

- Check provider is enabled in `.env` (`SECURE_MESSAGING_TELEGRAM_ENABLED`, etc.)
- Verify provider credentials in secrets
- Check rate limiting isn't blocking (default 30/min per app)
- Review logs for sanitized error messages

## Security Considerations

- **Never** expose secure_messaging_api publicly
- **Never** mount provider credentials into consuming services
- Each consuming service gets only its own client token
- Tokens should be long random strings
- Rotate tokens periodically

## Future Enhancements

Potential improvements (not yet implemented):
- Redis-backed distributed rate limiting for multi-replica
- Per-app provider permissions
- Deduplication windows for repeated notifications
- Optional dry-run mode for staging
