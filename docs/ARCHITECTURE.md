# Architecture Overview

This document explains the modular architecture of the Swarm Python API Template.

## Design Philosophy

The template uses a **modular composition** approach instead of maintaining multiple complete configuration files. This provides:

1. **No Redundancy** - Each configuration option is defined once
2. **Easy Maintenance** - Update one module to affect all combinations
3. **Clear Separation** - Database, proxy, and base configs are isolated
4. **Flexibility** - Easy to add new options without exponential file growth

## Configuration Matrix

The template supports these combinations:

| Database | Mode | Proxy | Result |
|----------|------|-------|--------|
| PostgreSQL | Local | Traefik | PostgreSQL deployed in swarm with Traefik routing |
| PostgreSQL | Local | None | PostgreSQL deployed in swarm with direct port |
| PostgreSQL | External | Traefik | Connect to external PostgreSQL with Traefik routing |
| PostgreSQL | External | None | Connect to external PostgreSQL with direct port |
| Neo4j | Local | Traefik | Neo4j deployed in swarm with Traefik routing |
| Neo4j | Local | None | Neo4j deployed in swarm with direct port |
| Neo4j | External | Traefik | Connect to external Neo4j with Traefik routing |
| Neo4j | External | None | Connect to external Neo4j with direct port |

**Total combinations**: 8

**Without modular approach**: Would require 8 complete template files

**With modular approach**: Only 8 small module files + 1 base template

## File Structure

```
setup/
├── compose-modules/          # Modular compose files
│   ├── base.yml             # Common services (Redis, networks, secrets)
│   ├── api-base.yml         # Base API configuration
│   ├── postgres-local.yml   # PostgreSQL local deployment
│   ├── postgres-external.yml # PostgreSQL external connection
│   ├── neo4j-local.yml      # Neo4j local deployment
│   ├── neo4j-external.yml   # Neo4j external connection
│   ├── proxy-traefik.yml    # Traefik configuration
│   ├── proxy-none.yml       # Direct port exposure
│   └── README.md            # Module documentation
├── env-templates/           # Environment variable templates
│   ├── .env.base.template
│   ├── .env.postgres-local.template
│   ├── .env.postgres-external.template
│   ├── .env.neo4j-local.template
│   ├── .env.neo4j-external.template
│   ├── .env.proxy-traefik.template
│   └── .env.proxy-none.template
└── swarm-stack.yml.template # Main template with includes
```

## How Modules Are Combined

### Example 1: PostgreSQL Local + Traefik

**Generated swarm-stack.yml:**
```yaml
include:
  - compose-modules/base.yml
  - compose-modules/api-base.yml
  - compose-modules/postgres-local.yml
  - compose-modules/proxy-traefik.yml
```

**Generated .env:**
```bash
# From .env.base.template
API_REPLICAS=1
REDIS_REPLICAS=1
IMAGE_NAME=...
# ...

# From .env.postgres-local.template
POSTGRES_REPLICAS=1
DB_TYPE=postgresql
DB_NAME=apidb
# ...

# From .env.proxy-traefik.template
API_URL=api.example.com
TRAEFIK_NETWORK_NAME=traefik
```

**Result:**
- API service with Traefik labels
- PostgreSQL service deployed in swarm
- Redis service
- Traefik network connection
- Secrets for database password

### Example 2: Neo4j External + No Proxy

**Generated swarm-stack.yml:**
```yaml
include:
  - compose-modules/base.yml
  - compose-modules/api-base.yml
  - compose-modules/neo4j-external.yml
  - compose-modules/proxy-none.yml
```

**Generated .env:**
```bash
# From .env.base.template
API_REPLICAS=1
REDIS_REPLICAS=1
IMAGE_NAME=...
# ...

# From .env.neo4j-external.template
DB_TYPE=neo4j
DB_USER=neo4j
NEO4J_URL=bolt://external-host:7687
DB_PASSWORD=...

# From .env.proxy-none.template
PUBLISHED_PORT=8000
```

**Result:**
- API service with direct port exposure
- No database service (connects to external)
- Redis service
- No Traefik network
- Only Admin API key secret needed

## Docker Compose Include Mechanism

Docker Compose's `include` directive merges multiple YAML files:

1. **Base files are loaded first** (base.yml, api-base.yml)
2. **Specific modules override/extend** (database and proxy modules)
3. **Environment variables** are substituted from `.env`

### Merge Behavior

When the same service appears in multiple files:
- **Environment variables** are merged
- **Networks** are merged
- **Labels** are merged
- **Ports** are merged
- **Other properties** use the last defined value

Example:
```yaml
# api-base.yml
services:
  api:
    environment:
      PORT: ${PORT}
      DEBUG: ${DEBUG}

# postgres-local.yml
services:
  api:
    environment:
      DB_TYPE: postgresql
      DB_NAME: ${DB_NAME}

# Result: Both environment sections are merged
services:
  api:
    environment:
      PORT: ${PORT}
      DEBUG: ${DEBUG}
      DB_TYPE: postgresql
      DB_NAME: ${DB_NAME}
```

## Setup Wizard Flow

```
1. Database Type Selection
   ├─ PostgreSQL → Set DB_TYPE=postgresql
   └─ Neo4j → Set DB_TYPE=neo4j

2. Proxy Selection
   ├─ Traefik → PROXY_MODULE=proxy-traefik.yml
   └─ None → PROXY_MODULE=proxy-none.yml

3. Database Mode Selection
   ├─ Local → DATABASE_MODULE={db_type}-local.yml
   └─ External → DATABASE_MODULE={db_type}-external.yml

4. Build Configuration
   ├─ Concatenate .env templates
   ├─ Create swarm-stack.yml with includes
   └─ Prompt for specific values

5. Collect Configuration Values
   ├─ Image name/version
   ├─ Domain (Traefik) or Port (No proxy)
   ├─ Data root path
   ├─ Stack name
   ├─ Database credentials (local or external)
   └─ Replica counts

6. Generate Final Files
   ├─ .env (with all values filled)
   └─ swarm-stack.yml (with correct module includes)
```

## Adding New Options

### Adding a New Database Type (e.g., MongoDB)

1. **Create module files:**
   ```bash
   setup/compose-modules/mongodb-local.yml
   setup/compose-modules/mongodb-external.yml
   ```

2. **Create env templates:**
   ```bash
   setup/env-templates/.env.mongodb-local.template
   setup/env-templates/.env.mongodb-external.template
   ```

3. **Update setup.sh:**
   ```bash
   # Add MongoDB option to database selection
   echo "3) MongoDB (document database)"
   
   # Add case for MongoDB
   3)
       DB_TYPE="mongodb"
       echo "✅ Selected: MongoDB"
       ;;
   ```

4. **Update module selection logic:**
   ```bash
   elif [ "$DB_TYPE" = "mongodb" ]; then
       if [ "$DB_MODE" = "local" ]; then
           cat setup/env-templates/.env.mongodb-local.template >> .env
           DATABASE_MODULE="mongodb-local.yml"
       else
           cat setup/env-templates/.env.mongodb-external.template >> .env
           DATABASE_MODULE="mongodb-external.yml"
       fi
   fi
   ```

### Adding a New Proxy Type (e.g., nginx)

1. **Create module file:**
   ```bash
   setup/compose-modules/proxy-nginx.yml
   ```

2. **Create env template:**
   ```bash
   setup/env-templates/.env.proxy-nginx.template
   ```

3. **Update setup.sh:**
   ```bash
   # Add nginx option to proxy selection
   echo "3) nginx (custom reverse proxy)"
   
   # Add case for nginx
   3)
       PROXY_TYPE="nginx"
       echo "✅ Selected: nginx"
       ;;
   ```

4. **Update module selection logic:**
   ```bash
   elif [ "$PROXY_TYPE" = "nginx" ]; then
       cat setup/env-templates/.env.proxy-nginx.template >> .env
       PROXY_MODULE="proxy-nginx.yml"
   fi
   ```

## Benefits Over Previous Approach

### Before (Monolithic Templates)

```
setup/
├── swarm-stack.postgres.traefik.yml.template      (115 lines)
├── swarm-stack.postgres.no-proxy.yml.template     (115 lines)
├── swarm-stack.neo4j.traefik.yml.template         (122 lines)
├── swarm-stack.neo4j.no-proxy.yml.template        (122 lines)
├── .env.postgres.traefik.template
├── .env.postgres.no-proxy.template
├── .env.neo4j.traefik.template
└── .env.neo4j.no-proxy.template

Total: 4 complete stack files (474 lines)
Problem: Adding external DB option = 8 files (948 lines)
```

### After (Modular Approach)

```
setup/
├── compose-modules/
│   ├── base.yml                    (25 lines)
│   ├── api-base.yml                (40 lines)
│   ├── postgres-local.yml          (35 lines)
│   ├── postgres-external.yml       (15 lines)
│   ├── neo4j-local.yml             (45 lines)
│   ├── neo4j-external.yml          (10 lines)
│   ├── proxy-traefik.yml           (20 lines)
│   └── proxy-none.yml              (8 lines)
├── swarm-stack.yml.template        (7 lines)
└── .env templates (7 small files)

Total: 8 module files (198 lines) + 1 template
Benefit: All 8 combinations covered with less code
```

## Security Considerations

### Local Database
- Database password stored in Docker secrets
- Password never in `.env` file
- Secrets mounted as files in containers

### External Database
- Database password in `.env` file (encrypted at rest recommended)
- Alternative: Use Docker secrets for external DB password too
- Ensure `.env` is in `.gitignore`

## Performance Considerations

- **Include overhead**: Minimal, processed at deploy time
- **Module count**: No runtime impact, merged before deployment
- **Network topology**: Same as monolithic approach
- **Resource usage**: Identical to monolithic templates

## Troubleshooting

### Issue: Include files not found

**Symptom**: `Error: include file not found`

**Solution**: Ensure you're deploying from the repository root where `swarm-stack.yml` can find `compose-modules/` directory

### Issue: Environment variables not substituted

**Symptom**: Variables like `${PORT}` appear literally in deployed services

**Solution**: Ensure `.env` file exists and contains all required variables

### Issue: Service configuration not as expected

**Symptom**: Service missing expected configuration

**Solution**: Check which modules are included in `swarm-stack.yml` and verify module contents

## References

- [Docker Compose Include Documentation](https://docs.docker.com/reference/compose-file/include/)
- [Docker Compose Merge Behavior](https://docs.docker.com/reference/compose-file/merge/)
- [Docker Swarm Stack Deploy](https://docs.docker.com/engine/reference/commandline/stack_deploy/)
