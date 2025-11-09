# Project Structure

## Directory Layout

```
swarm-python-api-template/
├── docs/                           # Documentation
│   ├── ARCHITECTURE.md            # Modular architecture explanation
│   ├── PROXY_SETUP.md             # Proxy configuration guide
│   └── STRUCTURE.md               # This file
│
├── setup/                          # Configuration templates
│   ├── compose-modules/           # Modular Docker Compose files
│   │   ├── README.md             # Module documentation
│   │   ├── base.yml              # Common services (Redis, networks)
│   │   ├── api-base.yml          # Base API configuration
│   │   ├── postgres-local.yml    # PostgreSQL local deployment
│   │   ├── postgres-external.yml # PostgreSQL external connection
│   │   ├── neo4j-local.yml       # Neo4j local deployment
│   │   ├── neo4j-external.yml    # Neo4j external connection
│   │   ├── proxy-traefik.yml     # Traefik proxy configuration
│   │   └── proxy-none.yml        # Direct port exposure
│   │
│   ├── env-templates/             # Environment variable templates
│   │   ├── .env.base.template              # Base configuration
│   │   ├── .env.postgres-local.template    # PostgreSQL local settings
│   │   ├── .env.postgres-external.template # PostgreSQL external settings
│   │   ├── .env.neo4j-local.template       # Neo4j local settings
│   │   ├── .env.neo4j-external.template    # Neo4j external settings
│   │   ├── .env.proxy-traefik.template     # Traefik settings
│   │   └── .env.proxy-none.template        # No-proxy settings
│   │
│   └── swarm-stack.yml.template  # Main stack template (uses includes)
│
├── interactive-scripts/           # Setup wizard
│   ├── docker-compose.setup.yml  # Setup container configuration
│   └── setup.sh                  # Interactive setup script (executable)
│
├── quick-start.sh                # Quick start script (Linux/Mac) (executable)
├── quick-start.ps1               # Quick start script (Windows) (executable)
├── README.md                     # Main documentation
└── .gitignore                    # Git ignore rules

Generated files (not in repo):
├── .env                          # Your environment configuration
├── swarm-stack.yml              # Your stack configuration
└── .setup-complete              # Setup completion marker

Note: Shell scripts (.sh) are marked as executable in git and can be run 
directly after cloning. If you encounter permission issues, use:
  - bash quick-start.sh (Linux/Mac/Git Bash)
  - powershell -ExecutionPolicy Bypass -File .\quick-start.ps1 (Windows)
```

## Configuration Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    User Runs Setup Wizard                    │
│                  (./quick-start.sh or setup.sh)              │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    User Makes Choices                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Database    │  │    Proxy     │  │   DB Mode    │      │
│  │  PostgreSQL  │  │   Traefik    │  │    Local     │      │
│  │  or Neo4j    │  │  or None     │  │  or External │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              Setup Script Builds Configuration               │
│                                                               │
│  1. Concatenate .env templates:                              │
│     .env.base.template                                       │
│     + .env.{database}-{mode}.template                        │
│     + .env.proxy-{type}.template                             │
│     = .env                                                   │
│                                                               │
│  2. Create swarm-stack.yml:                                  │
│     Copy swarm-stack.yml.template                            │
│     Replace XXX_DATABASE_MODULE_XXX                          │
│     Replace XXX_PROXY_MODULE_XXX                             │
│     = swarm-stack.yml                                        │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                  User Provides Values                        │
│  • Image name/version                                        │
│  • Domain (Traefik) or Port (No proxy)                      │
│  • Data root path                                            │
│  • Stack name                                                │
│  • Database credentials                                      │
│  • Replica counts                                            │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              Generated Configuration Files                   │
│                                                               │
│  .env                    swarm-stack.yml                     │
│  ├─ Base settings        include:                            │
│  ├─ DB settings            - compose-modules/base.yml        │
│  └─ Proxy settings         - compose-modules/api-base.yml   │
│                            - compose-modules/{db}-{mode}.yml │
│                            - compose-modules/proxy-{type}.yml│
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    User Deploys Stack                        │
│         docker stack deploy -c swarm-stack.yml <NAME>        │
└─────────────────────────────────────────────────────────────┘
```

## Module Combination Examples

### Example 1: PostgreSQL Local + Traefik

```
User Choices:
├─ Database: PostgreSQL
├─ Proxy: Traefik
└─ Mode: Local

Generated .env:
├─ .env.base.template
├─ .env.postgres-local.template
└─ .env.proxy-traefik.template

Generated swarm-stack.yml includes:
├─ compose-modules/base.yml
├─ compose-modules/api-base.yml
├─ compose-modules/postgres-local.yml
└─ compose-modules/proxy-traefik.yml

Deployed Services:
├─ api (with Traefik labels)
├─ postgres (in swarm)
└─ redis

Networks:
├─ backend (overlay)
└─ traefik (external)

Secrets:
├─ DB_PASSWORD_xxx
└─ ADMIN_API_KEY_xxx
```

### Example 2: Neo4j External + No Proxy

```
User Choices:
├─ Database: Neo4j
├─ Proxy: None
└─ Mode: External

Generated .env:
├─ .env.base.template
├─ .env.neo4j-external.template
└─ .env.proxy-none.template

Generated swarm-stack.yml includes:
├─ compose-modules/base.yml
├─ compose-modules/api-base.yml
├─ compose-modules/neo4j-external.yml
└─ compose-modules/proxy-none.yml

Deployed Services:
├─ api (with port exposure)
└─ redis

Networks:
└─ backend (overlay)

Secrets:
└─ ADMIN_API_KEY_xxx

External Dependencies:
└─ Neo4j server (user-managed)
```

## File Size Comparison

### Monolithic Approach (Old)
```
4 database variations × 2 proxy types = 8 complete files
Each file: ~115 lines
Total: ~920 lines of mostly duplicated code
```

### Modular Approach (New)
```
8 small module files: ~200 lines total
7 env templates: ~150 lines total
1 main template: 7 lines
Total: ~357 lines with no duplication
```

**Reduction: 61% less code, 100% less duplication**

## Adding New Options

### To Add a New Database Type:

1. Create 2 module files in `setup/compose-modules/`:
   - `{database}-local.yml`
   - `{database}-external.yml`

2. Create 2 env templates in `setup/`:
   - `.env.{database}-local.template`
   - `.env.{database}-external.template`

3. Update `setup.sh` to include new option

**Result**: Support for new database with 4 small files

### To Add a New Proxy Type:

1. Create 1 module file in `setup/compose-modules/`:
   - `proxy-{type}.yml`

2. Create 1 env template in `setup/`:
   - `.env.proxy-{type}.template`

3. Update `setup.sh` to include new option

**Result**: Support for new proxy with 2 small files

## Key Benefits

1. **Maintainability**: Update one module, affect all combinations
2. **Clarity**: Each file has a single, clear purpose
3. **Extensibility**: Easy to add new options
4. **No Duplication**: Each configuration defined once
5. **Testability**: Test individual modules independently
6. **Documentation**: Smaller files are easier to understand

## Quick Reference

| Need to... | Edit this file... |
|------------|------------------|
| Change Redis version | `setup/compose-modules/base.yml` |
| Change API base config | `setup/compose-modules/api-base.yml` |
| Change PostgreSQL settings | `setup/compose-modules/postgres-*.yml` |
| Change Neo4j settings | `setup/compose-modules/neo4j-*.yml` |
| Change Traefik labels | `setup/compose-modules/proxy-traefik.yml` |
| Change port exposure | `setup/compose-modules/proxy-none.yml` |
| Add new database type | Create new modules + update setup.sh |
| Add new proxy type | Create new modules + update setup.sh |
