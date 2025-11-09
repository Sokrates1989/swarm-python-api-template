# Setup Directory

This directory contains all configuration templates and modular components for setting up your Docker Swarm deployment.

## Directory Structure

```
setup/
├── compose-modules/        # Modular Docker Compose files
│   ├── base.yml           # Base structure (services: + redis)
│   ├── api.template.yml   # API service template
│   ├── footer.yml         # Networks and secrets
│   ├── postgres-local.yml # PostgreSQL service
│   ├── neo4j-local.yml    # Neo4j service
│   ├── snippets/          # Configuration snippets
│   │   ├── db-*.env.yml   # Database environment variables
│   │   └── proxy-*.yml    # Proxy configurations
│   └── README.md          # Compose modules documentation
├── env-templates/         # Environment variable templates
│   ├── .env.base.template
│   ├── .env.postgres-local.template
│   ├── .env.neo4j-local.template
│   ├── .env.proxy-*.template
│   └── README.md          # Environment templates documentation
└── modules/               # Reusable script modules
    ├── config-builder.sh/.ps1    # Configuration file builders
    ├── data-dirs.sh/.ps1         # Data directory creation
    ├── deploy-stack.sh/.ps1      # Stack deployment & health checks
    ├── network-check.sh/.ps1     # DNS verification
    ├── secret-manager.sh/.ps1    # Docker secret management
    └── user-prompts.sh/.ps1      # User input collection
```

## Usage

### Automated Setup (Recommended)

Run the setup wizard from the project root:

```bash
# Linux/Mac
./setup-wizard.sh

# Windows PowerShell
.\setup-wizard.ps1
```

The setup wizards are now modular and platform-specific:
- **`setup-wizard.sh`** - For Linux/Mac (Bash)
- **`setup-wizard.ps1`** - For Windows (PowerShell)

The interactive wizard will:
1. Check for existing setup and offer to backup
2. Ask about your database type (PostgreSQL or Neo4j)
3. Ask about database mode (local or external)
4. Ask about proxy type (Traefik or none)
5. Build `.env` from modular templates
6. Build `swarm-stack.yml` using template injection
7. Collect deployment parameters (stack name, image, replicas, etc.)
8. Guide you through Docker secret creation
9. Verify network configuration (for Traefik)
10. Create required data directories
11. Deploy the stack to Docker Swarm
12. Perform health checks on deployed services

### What Gets Generated

After running the setup wizard, you'll have:

- **`.env`** - Merged environment variables from selected templates
- **`swarm-stack.yml`** - Complete Docker Swarm stack configuration
- **`.setup-complete`** - Marker file indicating setup completion

### Deployment Process

The generated `swarm-stack.yml` is ready for deployment:

```bash
# Method 1: Direct deployment with variable substitution
docker stack deploy -c <(docker-compose -f swarm-stack.yml config) <STACK_NAME>

# Method 2: Generate merged file first (useful for inspection)
docker-compose -f swarm-stack.yml config > merged-stack.yml
docker stack deploy -c merged-stack.yml <STACK_NAME>
```

## How It Works

The setup wizard uses a **modular architecture** with reusable components:

### Modular Components

Each module handles a specific responsibility:

- **`user-prompts`** - Collects all user input with validation
- **`config-builder`** - Builds `.env` and `swarm-stack.yml` from templates
- **`network-check`** - Verifies DNS resolution for Traefik domains
- **`data-dirs`** - Creates required data directories with proper checks
- **`secret-manager`** - Handles Docker secret creation
- **`deploy-stack`** - Deploys stack and performs health checks

### Template System

1. **Environment Variables**: Concatenates `.env` templates based on your choices
2. **Compose Files**: Uses template injection to build a valid `swarm-stack.yml`:
   - Starts with `base.yml` (services: + redis)
   - Injects snippets into `api.template.yml` based on database/proxy choices
   - Adds database service module (if local deployment)
   - Closes with `footer.yml` (networks: + secrets:)

### Benefits

- ✅ **Maintainable**: Each module has a single responsibility
- ✅ **Cross-platform**: Separate implementations for Bash and PowerShell
- ✅ **No duplication**: Shared logic in modules, not repeated in wizards
- ✅ **Testable**: Modules can be tested independently
- ✅ **Extensible**: Easy to add new database types or proxy options

## Manual Setup

If you prefer manual configuration, see the main README.md for detailed instructions.

## Troubleshooting

If setup fails or you want to start over:

```bash
# Remove generated files
rm -f .env swarm-stack.yml .setup-complete

# Run setup wizard again
./setup/setup-wizard.sh
```

For more details on the modular system, see `compose-modules/README.md`.
