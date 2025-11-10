# Testing Scenarios for Setup Wizard

This document outlines test scenarios to verify the setup wizard correctly builds `swarm-stack.yml` files with proper Traefik labels and proxy configurations.

## Test Scenarios

### Scenario 1: PostgreSQL Local + Traefik
**Configuration:**
- Database: PostgreSQL
- Database Mode: Local
- Proxy: Traefik

**Expected Result:**
```yaml
services:
  redis:
    # ... redis config
  
  api:
    image: ${IMAGE_NAME}:${IMAGE_VERSION}
    networks:
      - backend
      - XXX_CHANGE_ME_TRAEFIK_NETWORK_NAME_XXX  # Should be replaced with actual network
    secrets:
      - "XXX_CHANGE_ME_DB_PASSWORD_XXX"  # Should be replaced with actual secret
      - "XXX_CHANGE_ME_ADMIN_API_KEY_XXX"
    environment:
      # ... environment variables including PostgreSQL local config
      DB_HOST: ${STACK_NAME}_postgres
    deploy:
      mode: replicated
      replicas: ${API_REPLICAS}
      update_config:
        parallelism: 1
        delay: 10s
        order: start-first
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
      labels:
        - traefik.enable=true
        - traefik.constraint-label=traefik-public
        - traefik.docker.network=${TRAEFIK_NETWORK}
        - traefik.http.routers.${STACK_NAME}_api.service=${STACK_NAME}_api
        - traefik.http.services.${STACK_NAME}_api.loadbalancer.server.port=${PORT}
        - traefik.http.routers.${STACK_NAME}_api.rule=Host(`${API_URL}`)
        - traefik.http.routers.${STACK_NAME}_api.entrypoints=https,http,web
        - traefik.http.routers.${STACK_NAME}_api.tls=true
        - traefik.http.routers.${STACK_NAME}_api.tls.certresolver=le
        - "autoscale=true"
        - "autoscale.minimum_replicas=1"
        - "autoscale.maximum_replicas=5"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health').read()"]
  
  postgres:
    # ... postgres service definition

networks:
  backend:
    driver: overlay
  XXX_CHANGE_ME_TRAEFIK_NETWORK_NAME_XXX:  # Should be replaced with actual network
    external: true

secrets:
  "XXX_CHANGE_ME_DB_PASSWORD_XXX":
    external: true
  "XXX_CHANGE_ME_ADMIN_API_KEY_XXX":
    external: true
```

**Key Checks:**
- ✅ Traefik labels are present under `deploy.labels`
- ✅ NO `###PROXY_LABELS###` placeholder remains
- ✅ NO `###PROXY_PORTS###` placeholder remains
- ✅ NO `ports:` section in api service
- ✅ Traefik network is in api service networks
- ✅ PostgreSQL environment variables are present
- ✅ PostgreSQL service is included

---

### Scenario 2: PostgreSQL Local + No Proxy (Direct Port)
**Configuration:**
- Database: PostgreSQL
- Database Mode: Local
- Proxy: None

**Expected Result:**
```yaml
services:
  redis:
    # ... redis config
  
  api:
    image: ${IMAGE_NAME}:${IMAGE_VERSION}
    networks:
      - backend
    secrets:
      - "XXX_CHANGE_ME_DB_PASSWORD_XXX"
      - "XXX_CHANGE_ME_ADMIN_API_KEY_XXX"
    environment:
      # ... environment variables including PostgreSQL local config
      DB_HOST: ${STACK_NAME}_postgres
    ports:
      - target: ${PORT}
        published: ${PUBLISHED_PORT}
        protocol: tcp
        mode: host
    deploy:
      mode: replicated
      replicas: ${API_REPLICAS}
      update_config:
        parallelism: 1
        delay: 10s
        order: start-first
      restart_policy:
        condition: on-failure
        delay: 5s
        max_attempts: 3
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health').read()"]
  
  postgres:
    # ... postgres service definition

networks:
  backend:
    driver: overlay

secrets:
  "XXX_CHANGE_ME_DB_PASSWORD_XXX":
    external: true
  "XXX_CHANGE_ME_ADMIN_API_KEY_XXX":
    external: true
```

**Key Checks:**
- ✅ `ports:` section is present in api service
- ✅ NO `###PROXY_LABELS###` placeholder remains
- ✅ NO `###PROXY_PORTS###` placeholder remains
- ✅ NO traefik labels under deploy
- ✅ NO traefik network in networks section
- ✅ PostgreSQL environment variables are present
- ✅ PostgreSQL service is included

---

### Scenario 3: PostgreSQL External + Traefik
**Configuration:**
- Database: PostgreSQL
- Database Mode: External
- Proxy: Traefik

**Expected Result:**
```yaml
services:
  redis:
    # ... redis config
  
  api:
    image: ${IMAGE_NAME}:${IMAGE_VERSION}
    networks:
      - backend
      - XXX_CHANGE_ME_TRAEFIK_NETWORK_NAME_XXX
    secrets:
      - "XXX_CHANGE_ME_DB_PASSWORD_XXX"
      - "XXX_CHANGE_ME_ADMIN_API_KEY_XXX"
    environment:
      # ... environment variables including PostgreSQL external config
      DB_HOST: ${DB_HOST}  # External host
    deploy:
      mode: replicated
      replicas: ${API_REPLICAS}
      labels:
        - traefik.enable=true
        # ... all traefik labels

networks:
  backend:
    driver: overlay
  XXX_CHANGE_ME_TRAEFIK_NETWORK_NAME_XXX:
    external: true

secrets:
  "XXX_CHANGE_ME_DB_PASSWORD_XXX":
    external: true
  "XXX_CHANGE_ME_ADMIN_API_KEY_XXX":
    external: true
```

**Key Checks:**
- ✅ Traefik labels are present
- ✅ NO PostgreSQL service definition (external database)
- ✅ External database environment variables (DB_HOST, DB_PORT, etc.)
- ✅ NO `###PROXY_LABELS###` or `###PROXY_PORTS###` placeholders

---

### Scenario 4: Neo4j Local + Traefik
**Configuration:**
- Database: Neo4j
- Database Mode: Local
- Proxy: Traefik

**Expected Result:**
```yaml
services:
  redis:
    # ... redis config
  
  api:
    # ... with Neo4j environment variables
    environment:
      DB_TYPE: ${DB_TYPE}
      DB_MODE: local
      NEO4J_URI: ${NEO4J_URI}
      NEO4J_USERNAME: ${NEO4J_USERNAME}
      NEO4J_PASSWORD_FILE: /run/secrets/XXX_CHANGE_ME_DB_PASSWORD_XXX
    deploy:
      labels:
        - traefik.enable=true
        # ... all traefik labels
  
  neo4j:
    # ... neo4j service definition

networks:
  backend:
    driver: overlay
  XXX_CHANGE_ME_TRAEFIK_NETWORK_NAME_XXX:
    external: true
```

**Key Checks:**
- ✅ Traefik labels are present
- ✅ Neo4j service is included
- ✅ Neo4j environment variables are present
- ✅ NO placeholders remain

---

## Testing Procedure

### Manual Test
1. Run the setup wizard:
   ```bash
   ./setup/setup-wizard.sh
   # OR
   .\setup\setup-wizard.ps1
   ```

2. Select the scenario configuration when prompted

3. After wizard completes, inspect `swarm-stack.yml`:
   ```bash
   cat swarm-stack.yml
   ```

4. Verify against the expected result for your scenario

### Automated Checks
Run these commands to verify no placeholders remain:
```bash
# Check for unreplaced placeholders
grep -n "###" swarm-stack.yml
# Should return: no results

# For Traefik setup, verify labels exist
grep -n "traefik.enable" swarm-stack.yml
# Should return: line with traefik.enable=true

# For No Proxy setup, verify ports exist
grep -n "ports:" swarm-stack.yml
# Should return: line with ports section
```

### Validation Script
```bash
# Create a simple validation script
#!/bin/bash
STACK_FILE="swarm-stack.yml"

echo "Validating swarm-stack.yml..."

# Check for unreplaced placeholders
if grep -q "###" "$STACK_FILE"; then
    echo "❌ ERROR: Found unreplaced placeholders:"
    grep -n "###" "$STACK_FILE"
    exit 1
else
    echo "✅ No placeholders found"
fi

# Validate YAML syntax
if command -v docker &> /dev/null; then
    if docker stack config -c "$STACK_FILE" > /dev/null 2>&1; then
        echo "✅ Valid Docker Compose YAML"
    else
        echo "❌ ERROR: Invalid YAML syntax"
        exit 1
    fi
fi

echo "✅ Validation complete"
```

---

## Common Issues

### Issue 1: `###PROXY_LABELS###` remains in output
**Cause:** The config-builder script is not correctly injecting the labels snippet.
**Fix:** Verify the sed command targets `###PROXY_LABELS###` (not `###PROXY_CONFIG###`)

### Issue 2: `###PROXY_PORTS###` remains in output
**Cause:** The config-builder script is not correctly injecting the ports snippet.
**Fix:** Verify the sed command targets `###PROXY_PORTS###` (not `###PROXY_CONFIG###`)

### Issue 3: Both labels AND ports appear
**Cause:** The script is not removing the unused placeholder.
**Fix:** Ensure the script removes `###PROXY_PORTS###` when using Traefik, and removes `###PROXY_LABELS###` when using direct ports.

### Issue 4: Network placeholder not replaced
**Cause:** The `update_stack_network` function is not being called or failing.
**Fix:** Verify `update_stack_network` is called AFTER `build_stack_file` and with correct network name.

---

## Reference: Correct File Structure

The setup wizard should use these files:

### Primary Build Flow:
1. `base.yml` → base structure with services: key
2. `api.template.yml` → API service with placeholders
3. **Inject** `snippets/db-{type}-{mode}.env.yml` → database environment
4. **Inject** `snippets/proxy-traefik.network.yml` → traefik network (if traefik)
5. **Inject** `snippets/proxy-traefik.labels.yml` OR `snippets/proxy-none.ports.yml` → proxy config
6. `{db}-local.yml` → database service (if local)
7. `footer.yml` → networks and secrets

### Deprecated (Do Not Use):
- ❌ `proxy-traefik.yml` (full service, not snippet)
- ❌ `proxy-none.yml` (full service, not snippet)
- ❌ `api-base.yml` (old template without placeholders)
