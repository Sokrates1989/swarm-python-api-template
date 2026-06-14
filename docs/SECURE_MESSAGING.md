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

## Consuming Service Integration

### Docker Compose Snippet

Services that need to send notifications must:
1. Attach to `secure_messaging_internal` network
2. Mount their client token secret
3. Know the API URL

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

### API Call Example

From within the consuming service:

```bash
#!/bin/sh
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
