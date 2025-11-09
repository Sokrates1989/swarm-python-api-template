# Setup Directory

This directory contains all configuration templates and modules for setting up your Docker Swarm deployment.

## Directory Structure

```
setup/
├── compose-modules/        # Modular Docker Compose files
│   ├── base.yml           # Base structure (services: + redis)
│   ├── api.template.yml   # API service template
│   ├── footer.yml         # Networks and secrets
│   ├── postgres-local.yml # PostgreSQL service
│   ├── neo4j-local.yml    # Neo4j service
│   └── snippets/          # Configuration snippets
│       ├── db-*.env.yml   # Database environment variables
│       └── proxy-*.yml    # Proxy configurations
├── env-templates/         # Environment variable templates
│   ├── .env.base.template
│   ├── .env.postgres-local.template
│   ├── .env.neo4j-local.template
│   └── .env.proxy-*.template
├── setup-wizard.sh        # Interactive setup (Linux/Mac)
└── setup-wizard.ps1       # Interactive setup (Windows)
```

## Usage

### Automated Setup (Recommended)

Run the setup wizard from the project root:

```bash
# Linux/Mac
./setup/setup-wizard.sh

# Windows
.\setup\setup-wizard.ps1
```

Or use the quick-start scripts:

```bash
./quick-start.sh  # Linux/Mac
.\quick-start.ps1  # Windows
```

The interactive wizard will:
1. Ask about your database type (PostgreSQL or Neo4j)
2. Ask about database mode (local or external)
3. Ask about proxy type (Traefik or none)
4. Build `.env` from modular templates
5. Build `swarm-stack.yml` using template injection
6. Guide you through Docker secret creation
7. Provide deployment instructions

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

The setup wizard uses a **modular template system**:

1. **Environment Variables**: Concatenates `.env` templates based on your choices
2. **Compose Files**: Uses template injection to build a valid `swarm-stack.yml`:
   - Starts with `base.yml` (services: + redis)
   - Injects snippets into `api.template.yml` based on database/proxy choices
   - Adds database service module (if local deployment)
   - Closes with `footer.yml` (networks: + secrets:)

This approach ensures:
- ✅ No duplicate YAML keys
- ✅ Single source of truth for API configuration
- ✅ Easy maintenance (change once, affects all combinations)
- ✅ Valid YAML structure ready for `docker-compose config`

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
