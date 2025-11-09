# Project Structure

## Directory Layout

```
swarm-python-api-template/
├── docs/                           # Documentation
│   ├── ARCHITECTURE.md            # Modular architecture explanation
│   ├── MODULAR_SETUP_SUMMARY.md   # Setup system implementation summary
│   ├── PROXY_SETUP.md             # Proxy configuration guide
│   └── STRUCTURE.md               # This file
│
├── setup/                          # Configuration templates and modular components
│   ├── compose-modules/           # Modular Docker Compose files
│   │   ├── README.md             # Compose modules documentation
│   │   ├── base.yml              # Base structure (services: + Redis)
│   │   ├── api.template.yml      # API service template with placeholders
│   │   ├── footer.yml            # Networks and secrets definitions
│   │   ├── postgres-local.yml    # PostgreSQL local deployment
│   │   ├── neo4j-local.yml       # Neo4j local deployment
│   │   ├── proxy-traefik.yml     # Traefik proxy configuration (deprecated)
│   │   ├── proxy-none.yml        # Direct port exposure (deprecated)
│   │   └── snippets/             # Configuration snippets for injection
│   │       ├── db-postgresql-local.env.yml
│   │       ├── db-postgresql-external.env.yml
│   │       ├── db-neo4j-local.env.yml
│   │       ├── db-neo4j-external.env.yml
│   │       ├── proxy-traefik.network.yml
│   │       ├── proxy-traefik.labels.yml
│   │       └── proxy-none.ports.yml
│   │
│   ├── env-templates/             # Environment variable templates
│   │   ├── README.md                        # Environment templates documentation
│   │   ├── .env.base.template              # Base configuration
│   │   ├── .env.postgres-local.template    # PostgreSQL local settings
│   │   ├── .env.postgres-external.template # PostgreSQL external settings
│   │   ├── .env.neo4j-local.template       # Neo4j local settings
│   │   ├── .env.neo4j-external.template    # Neo4j external settings
│   │   ├── .env.proxy-traefik.template     # Traefik settings
│   │   └── .env.proxy-none.template        # No-proxy settings
│   │
│   ├── modules/                   # Reusable script modules
│   │   ├── README.md             # Module documentation
│   │   ├── config-builder.sh     # Configuration file builders (Bash)
│   │   ├── config-builder.ps1    # Configuration file builders (PowerShell)
│   │   ├── data-dirs.sh          # Data directory creation (Bash)
│   │   ├── data-dirs.ps1         # Data directory creation (PowerShell)
│   │   ├── deploy-stack.sh       # Stack deployment & health checks (Bash)
│   │   ├── deploy-stack.ps1      # Stack deployment & health checks (PowerShell)
│   │   ├── network-check.sh      # DNS verification (Bash)
│   │   ├── network-check.ps1     # DNS verification (PowerShell)
│   │   ├── secret-manager.sh     # Docker secret management (Bash)
│   │   ├── secret-manager.ps1    # Docker secret management (PowerShell)
│   │   ├── user-prompts.sh       # User input collection (Bash)
│   │   └── user-prompts.ps1      # User input collection (PowerShell)
│   │
│   └── README.md                  # Setup directory documentation
│
├── setup-wizard.sh                # Main setup wizard (Linux/Mac) (executable)
├── setup-wizard.ps1               # Main setup wizard (Windows) (executable)
├── README.md                      # Main documentation
└── .gitignore                     # Git ignore rules

Generated files (not in repo):
├── .env                          # Your environment configuration
├── swarm-stack.yml              # Your stack configuration
└── .setup-complete              # Setup completion marker

Note: Shell scripts (.sh) and PowerShell scripts (.ps1) are marked as executable 
in git and can be run directly after cloning. If you encounter permission issues, use:
  - chmod +x setup-wizard.sh && ./setup-wizard.sh (Linux/Mac)
  - bash setup-wizard.sh (Linux/Mac/Git Bash)
  - powershell -ExecutionPolicy Bypass -File .\setup-wizard.ps1 (Windows)
```

## Configuration Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    User Runs Setup Wizard                    │
│            (./setup-wizard.sh or .\setup-wizard.ps1)         │
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
│                                                               │
│  Modules used: user-prompts.sh/.ps1                          │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              Config Builder Builds Configuration             │
│                                                               │
│  1. Build .env (concatenate templates):                      │
│     .env.base.template                                       │
│     + .env.{database}-{mode}.template                        │
│     + .env.proxy-{type}.template                             │
│     = .env                                                   │
│                                                               │
│  2. Build swarm-stack.yml (template injection):              │
│     base.yml (services: + Redis)                             │
│     + api.template.yml with injected snippets:               │
│       - db-{database}-{mode}.env.yml                         │
│       - proxy-{type}.network.yml (if Traefik)                │
│       - proxy-{type}.labels/ports.yml                        │
│     + {database}-local.yml (if local mode)                   │
│     + footer.yml (networks: + secrets:)                      │
│     = swarm-stack.yml                                        │
│                                                               │
│  Modules used: config-builder.sh/.ps1                        │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                  User Provides Values                        │
│  • Stack name                                                │
│  • Data root path                                            │
│  • Image name/version (with verification)                    │
│  • Domain (Traefik) or Port (No proxy)                      │
│  • Replica counts (API, DB, Redis)                          │
│  • Secret names                                              │
│                                                               │
│  Modules used: user-prompts.sh/.ps1                          │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                  Secret Manager Creates Secrets              │
│  • Database password secret (if local DB)                    │
│  • Admin API key secret                                      │
│                                                               │
│  Modules used: secret-manager.sh/.ps1                        │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              Network Check Verifies DNS (Traefik)            │
│  • Resolve domain to IP                                      │
│  • Confirm IP matches swarm manager                          │
│                                                               │
│  Modules used: network-check.sh/.ps1                         │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              Data Dirs Creates Directories                   │
│  • Data root directory                                       │
│  • Database-specific directories                             │
│  • Redis data directory                                      │
│                                                               │
│  Modules used: data-dirs.sh/.ps1                             │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              Deploy Stack Deploys & Verifies                 │
│  • Deploy to Docker Swarm                                    │
│  • Check service replicas                                    │
│  • Inspect service logs                                      │
│  • Test API health endpoint                                  │
│                                                               │
│  Modules used: deploy-stack.sh/.ps1                          │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    Deployment Complete!                      │
│  Configuration files: .env, swarm-stack.yml                  │
│  Stack deployed: <STACK_NAME>                                │
└─────────────────────────────────────────────────────────────┘
```

## Module Combination Examples

### Example 1: PostgreSQL Local + Traefik

```
User Choices:
├─ Database: PostgreSQL
├─ Proxy: Traefik
└─ Mode: Local

Generated .env (concatenated):
├─ .env.base.template
├─ .env.postgres-local.template
└─ .env.proxy-traefik.template

Generated swarm-stack.yml (template injection):
├─ base.yml (services: + Redis)
├─ api.template.yml with injected snippets:
│   ├─ db-postgresql-local.env.yml (environment variables)
│   ├─ proxy-traefik.network.yml (traefik network)
│   └─ proxy-traefik.labels.yml (Traefik labels)
├─ postgres-local.yml (PostgreSQL service)
└─ footer.yml (networks: + secrets:)

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

Generated .env (concatenated):
├─ .env.base.template
├─ .env.neo4j-external.template
└─ .env.proxy-none.template

Generated swarm-stack.yml (template injection):
├─ base.yml (services: + Redis)
├─ api.template.yml with injected snippets:
│   ├─ db-neo4j-external.env.yml (environment variables)
│   └─ proxy-none.ports.yml (port mapping)
└─ footer.yml (networks: + secrets:)

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

### Old Monolithic Wizards
```
setup/setup-wizard.sh: ~24KB (monolithic)
setup/setup-wizard.ps1: ~27KB (monolithic)
Total: ~51KB with duplicated logic
```

### New Modular System
```
Main Wizards:
├─ setup-wizard.sh: ~5KB (orchestrator)
└─ setup-wizard.ps1: ~5KB (orchestrator)

Modules (6 pairs, Bash + PowerShell):
├─ user-prompts: ~3KB each
├─ config-builder: ~4KB each
├─ network-check: ~2KB each
├─ data-dirs: ~3KB each
├─ secret-manager: ~3KB each
└─ deploy-stack: ~5KB each

Total: ~50KB with no duplication, modular structure
```

**Benefits:**
- 80% reduction in main wizard size
- 100% elimination of code duplication
- 6 focused, reusable modules
- Cross-platform feature parity

## Adding New Options

### To Add a New Database Type (e.g., MongoDB):

1. **Create compose module files** in `setup/compose-modules/`:
   - `mongodb-local.yml` (MongoDB service definition)

2. **Create snippet files** in `setup/compose-modules/snippets/`:
   - `db-mongodb-local.env.yml` (environment variables for local)
   - `db-mongodb-external.env.yml` (environment variables for external)

3. **Create env templates** in `setup/env-templates/`:
   - `.env.mongodb-local.template`
   - `.env.mongodb-external.template`

4. **Update user-prompts module**:
   - Add MongoDB option in `prompt_database_type()` / `Get-DatabaseType`

5. **Update config-builder module**:
   - Add MongoDB case in `build_env_file()` / `New-EnvFile`
   - Add MongoDB case in `build_stack_file()` / `New-StackFile`

**Result**: Support for new database with 5 small files + 2 module updates

### To Add a New Proxy Type (e.g., nginx):

1. **Create snippet files** in `setup/compose-modules/snippets/`:
   - `proxy-nginx.network.yml` (if needed)
   - `proxy-nginx.labels.yml` or `proxy-nginx.ports.yml`

2. **Create env template** in `setup/env-templates/`:
   - `.env.proxy-nginx.template`

3. **Update user-prompts module**:
   - Add nginx option in `prompt_proxy_type()` / `Get-ProxyType`

4. **Update config-builder module**:
   - Add nginx case in `build_env_file()` / `New-EnvFile`
   - Add nginx case in `build_stack_file()` / `New-StackFile`

**Result**: Support for new proxy with 2-3 small files + 2 module updates

## Key Benefits

### Modular Architecture
1. **Maintainability**: Each module has single responsibility
2. **Clarity**: Clear separation of concerns
3. **Extensibility**: Easy to add new database/proxy types
4. **No Duplication**: Shared logic in reusable modules
5. **Testability**: Test individual modules independently
6. **Cross-platform**: Feature parity between Bash and PowerShell

### Template Injection System
1. **Single Source of Truth**: API configuration in one template
2. **No Duplicate Keys**: Proper YAML structure
3. **Flexible**: Snippets can be mixed and matched
4. **Maintainable**: Change once, affects all combinations

## Quick Reference

### Configuration Files

| Need to... | Edit this file... |
|------------|------------------|
| Change Redis version | `setup/compose-modules/base.yml` |
| Change API base config | `setup/compose-modules/api.template.yml` |
| Change PostgreSQL settings | `setup/compose-modules/postgres-local.yml` |
| Change Neo4j settings | `setup/compose-modules/neo4j-local.yml` |
| Change Traefik labels | `setup/compose-modules/snippets/proxy-traefik.labels.yml` |
| Change port exposure | `setup/compose-modules/snippets/proxy-none.ports.yml` |
| Change DB environment vars | `setup/compose-modules/snippets/db-*.env.yml` |

### Setup Modules

| Need to... | Edit this module... |
|------------|---------------------|
| Change user prompts | `setup/modules/user-prompts.sh/.ps1` |
| Change config building | `setup/modules/config-builder.sh/.ps1` |
| Change DNS verification | `setup/modules/network-check.sh/.ps1` |
| Change directory creation | `setup/modules/data-dirs.sh/.ps1` |
| Change secret handling | `setup/modules/secret-manager.sh/.ps1` |
| Change deployment logic | `setup/modules/deploy-stack.sh/.ps1` |

### Adding New Features

| Want to add... | Steps... |
|----------------|----------|
| New database type | Create snippets + env templates + update user-prompts & config-builder |
| New proxy type | Create snippets + env template + update user-prompts & config-builder |
| New setup step | Create new module pair (Bash + PowerShell) + import in wizards |
