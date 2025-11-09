# Architecture Overview

This document explains the modular architecture of the Swarm Python API Template.

## Design Philosophy

The template uses a **two-layer modular approach**:

### Layer 1: Modular Setup Wizards
- Reusable script modules for setup process
- Cross-platform support (Bash + PowerShell)
- Single responsibility per module
- No code duplication between platforms

### Layer 2: Template Injection System
- Configuration snippets injected into templates
- No redundant YAML files
- Single source of truth for API configuration

This provides:

1. **No Redundancy** - Each configuration option is defined once
2. **Easy Maintenance** - Update one module/snippet to affect all combinations
3. **Clear Separation** - Database, proxy, and setup logic are isolated
4. **Flexibility** - Easy to add new options without exponential file growth
5. **Cross-platform** - Identical functionality on Windows, Linux, and Mac

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
swarm-python-api-template/
├── setup-wizard.sh          # Main wizard (Linux/Mac)
├── setup-wizard.ps1         # Main wizard (Windows)
│
└── setup/
    ├── compose-modules/     # Docker Compose templates
    │   ├── base.yml        # Base structure (services: + Redis)
    │   ├── api.template.yml # API template with placeholders
    │   ├── footer.yml      # Networks and secrets
    │   ├── postgres-local.yml # PostgreSQL service
    │   ├── neo4j-local.yml   # Neo4j service
    │   └── snippets/       # Configuration snippets
    │       ├── db-postgresql-local.env.yml
    │       ├── db-postgresql-external.env.yml
    │       ├── db-neo4j-local.env.yml
    │       ├── db-neo4j-external.env.yml
    │       ├── proxy-traefik.network.yml
    │       ├── proxy-traefik.labels.yml
    │       └── proxy-none.ports.yml
    │
    ├── env-templates/      # Environment variable templates
    │   ├── .env.base.template
    │   ├── .env.postgres-local.template
    │   ├── .env.postgres-external.template
    │   ├── .env.neo4j-local.template
    │   ├── .env.neo4j-external.template
    │   ├── .env.proxy-traefik.template
    │   └── .env.proxy-none.template
    │
    └── modules/            # Reusable script modules
        ├── user-prompts.sh/.ps1    # User input collection
        ├── config-builder.sh/.ps1  # Config file builders
        ├── network-check.sh/.ps1   # DNS verification
        ├── data-dirs.sh/.ps1       # Directory creation
        ├── secret-manager.sh/.ps1  # Secret management
        └── deploy-stack.sh/.ps1    # Deployment & health
```

## How Configuration is Built

### Template Injection Process

The `config-builder` module builds `swarm-stack.yml` using **template injection**:

1. Start with `base.yml` (services: + Redis)
2. Copy `api.template.yml` and inject snippets into placeholders:
   - `###DATABASE_ENV###` → database environment snippet
   - `###PROXY_NETWORK###` → proxy network snippet (if Traefik)
   - `###PROXY_CONFIG###` → proxy configuration snippet
3. Append database service (if local mode)
4. Append `footer.yml` (networks: + secrets:)

### Example 1: PostgreSQL Local + Traefik

**Generated swarm-stack.yml structure:**
```
base.yml (services: + Redis)
+ api.template.yml with injected:
  - db-postgresql-local.env.yml
  - proxy-traefik.network.yml
  - proxy-traefik.labels.yml
+ postgres-local.yml
+ footer.yml
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

**Generated swarm-stack.yml structure:**
```
base.yml (services: + Redis)
+ api.template.yml with injected:
  - db-neo4j-external.env.yml
  - proxy-none.ports.yml
+ footer.yml
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

## Setup Wizard Modules

The setup wizard uses 6 modular components:

### 1. user-prompts
- Collects all user input
- Database type, proxy type, database mode
- Stack name, image, replicas, secrets
- Domain (Traefik) or port (no proxy)

### 2. config-builder
- Builds `.env` by concatenating templates
- Builds `swarm-stack.yml` using template injection
- Updates configuration values
- Creates backups of existing files

### 3. network-check
- Verifies DNS resolution (Traefik only)
- Confirms IP matches swarm manager
- Allows proceeding if DNS not configured

### 4. data-dirs
- Creates data root directory
- Creates database-specific directories
- Creates Redis data directory
- Checks for existing directories

### 5. secret-manager
- Guides Docker secret creation
- Database password (local mode)
- Admin API key
- Lists existing secrets

### 6. deploy-stack
- Deploys stack to Docker Swarm
- Checks service replica status
- Inspects service logs
- Tests API health endpoint
- Provides deployment summary

## Template Injection Details

### API Template Structure

```yaml
# api.template.yml
services:
  api:
    image: ${IMAGE_NAME}:${IMAGE_VERSION}
    environment:
      PORT: ${PORT}
      ###DATABASE_ENV###
    networks:
      - backend
      ###PROXY_NETWORK###
    deploy:
      replicas: ${API_REPLICAS}
      ###PROXY_CONFIG###
```

### Snippet Injection

Placeholders are replaced with snippet content:

```yaml
# Before injection
###DATABASE_ENV###

# After injection (PostgreSQL local)
DB_TYPE: postgresql
DB_NAME: ${DB_NAME}
DB_USER: ${DB_USER}
```

## Setup Wizard Flow

```
1. User Input Collection (user-prompts module)
   ├─ Database Type: PostgreSQL or Neo4j
   ├─ Proxy Type: Traefik or None
   ├─ Database Mode: Local or External
   ├─ Stack name, data root, image
   ├─ Domain (Traefik) or Port (No proxy)
   ├─ Replica counts
   └─ Secret names

2. Configuration Building (config-builder module)
   ├─ Build .env:
   │   ├─ Concatenate .env.base.template
   │   ├─ Concatenate .env.{db}-{mode}.template
   │   └─ Concatenate .env.proxy-{type}.template
   │
   └─ Build swarm-stack.yml:
       ├─ Append base.yml
       ├─ Inject snippets into api.template.yml
       ├─ Append {db}-local.yml (if local)
       └─ Append footer.yml

3. Secret Creation (secret-manager module)
   ├─ Database password (if local DB)
   └─ Admin API key

4. Network Verification (network-check module)
   └─ Verify DNS resolution (if Traefik)

5. Directory Creation (data-dirs module)
   ├─ Data root
   ├─ Database directories
   └─ Redis directory

6. Deployment (deploy-stack module)
   ├─ Deploy to Docker Swarm
   ├─ Check service replicas
   ├─ Inspect logs
   └─ Test API health
```

## Adding New Options

### Adding a New Database Type (e.g., MongoDB)

1. **Create compose module:**
   ```bash
   setup/compose-modules/mongodb-local.yml
   ```

2. **Create snippets:**
   ```bash
   setup/compose-modules/snippets/db-mongodb-local.env.yml
   setup/compose-modules/snippets/db-mongodb-external.env.yml
   ```

3. **Create env templates:**
   ```bash
   setup/env-templates/.env.mongodb-local.template
   setup/env-templates/.env.mongodb-external.template
   ```

4. **Update user-prompts module:**
   ```bash
   # In prompt_database_type() / Get-DatabaseType
   echo "3) MongoDB (document database)"
   
   case $DB_CHOICE in
       3) echo "mongodb" ;;
   esac
   ```

5. **Update config-builder module:**
   ```bash
   # In build_env_file() / New-EnvFile
   elif [ "$db_type" = "mongodb" ]; then
       cat "${project_root}/setup/env-templates/.env.mongodb-${db_mode}.template" >> .env
   fi
   
   # In build_stack_file() / New-StackFile
   local db_env_snippet="${project_root}/setup/compose-modules/snippets/db-mongodb-${db_mode}.env.yml"
   ```

### Adding a New Proxy Type (e.g., nginx)

1. **Create snippets:**
   ```bash
   setup/compose-modules/snippets/proxy-nginx.network.yml  # if needed
   setup/compose-modules/snippets/proxy-nginx.labels.yml   # or ports
   ```

2. **Create env template:**
   ```bash
   setup/env-templates/.env.proxy-nginx.template
   ```

3. **Update user-prompts module:**
   ```bash
   # In prompt_proxy_type() / Get-ProxyType
   echo "3) nginx (custom reverse proxy)"
   
   case $PROXY_CHOICE in
       3) echo "nginx" ;;
   esac
   ```

4. **Update config-builder module:**
   ```bash
   # In build_env_file() / New-EnvFile
   elif [ "$proxy_type" = "nginx" ]; then
       cat "${project_root}/setup/env-templates/.env.proxy-nginx.template" >> .env
   fi
   
   # In build_stack_file() / New-StackFile
   local proxy_labels_snippet="${project_root}/setup/compose-modules/snippets/proxy-nginx.labels.yml"
   ```

## Benefits Over Previous Approach

### Before (Monolithic Wizards)

```
setup/
├── setup-wizard.sh                 (~24KB monolithic)
├── setup-wizard.ps1                (~27KB monolithic)
└── modules/ (3 basic modules)
    ├── data-dirs.sh/.ps1
    ├── deploy-stack.sh/.ps1
    └── network-check.sh/.ps1

Total: ~51KB with duplicated logic
Problems:
- All logic in two large scripts
- Code duplication between Bash/PowerShell
- Hard to maintain and test
- Difficult to add new features
```

### After (Modular System)

```
setup-wizard.sh                     (~5KB orchestrator)
setup-wizard.ps1                    (~5KB orchestrator)
setup/
├── compose-modules/
│   ├── base.yml, api.template.yml, footer.yml
│   ├── postgres-local.yml, neo4j-local.yml
│   └── snippets/ (7 snippet files)
├── env-templates/ (7 template files)
└── modules/ (6 comprehensive modules)
    ├── user-prompts.sh/.ps1        (~3KB each)
    ├── config-builder.sh/.ps1      (~4KB each)
    ├── network-check.sh/.ps1       (~2KB each)
    ├── data-dirs.sh/.ps1           (~3KB each)
    ├── secret-manager.sh/.ps1      (~3KB each)
    └── deploy-stack.sh/.ps1        (~5KB each)

Total: ~50KB with modular structure
Benefits:
- 80% reduction in main wizard size
- 100% elimination of code duplication
- 6 focused, testable modules
- Cross-platform feature parity
- Easy to add new databases/proxies
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
