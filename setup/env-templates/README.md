# Environment Variable Templates

This directory contains modular environment variable templates that are combined to create your final `.env` file.

## Template Files

### Base Configuration (Always Included)

- **`.env.base.template`** - Common settings for all deployments
  - API replicas
  - Redis replicas
  - Docker image configuration
  - Data root path
  - Stack name
  - Python version
  - API port settings
  - Redis URL

### Database Templates (Choose One Pair)

#### PostgreSQL
- **`.env.postgres-local.template`** - PostgreSQL deployed in swarm
  - PostgreSQL replicas
  - Database name, user, port
  
- **`.env.postgres-external.template`** - Connect to external PostgreSQL
  - Database host, name, user, port
  - Database password (stored in .env)

#### Neo4j
- **`.env.neo4j-local.template`** - Neo4j deployed in swarm
  - Neo4j replicas
  - Database user
  
- **`.env.neo4j-external.template`** - Connect to external Neo4j
  - Neo4j URL (bolt://...)
  - Database user and password

### Proxy Templates (Choose One)

- **`.env.proxy-traefik.template`** - Traefik proxy configuration
  - API domain (e.g., api.example.com)
  - Traefik network name

- **`.env.proxy-none.template`** - Direct port exposure
  - Published port on host

## How Templates Are Combined

The setup wizard concatenates templates based on your choices:

```bash
# Example: PostgreSQL local + Traefik
cat .env.base.template > ../../.env
cat .env.postgres-local.template >> ../../.env
cat .env.proxy-traefik.template >> ../../.env
```

```bash
# Example: Neo4j external + No proxy
cat .env.base.template > ../../.env
cat .env.neo4j-external.template >> ../../.env
cat .env.proxy-none.template >> ../../.env
```

## Manual Usage

If you're setting up manually:

1. **Start with base:**
   ```bash
   cat setup/env-templates/.env.base.template > .env
   ```

2. **Add database config (choose one):**
   ```bash
   cat setup/env-templates/.env.postgres-local.template >> .env
   # OR
   cat setup/env-templates/.env.postgres-external.template >> .env
   # OR
   cat setup/env-templates/.env.neo4j-local.template >> .env
   # OR
   cat setup/env-templates/.env.neo4j-external.template >> .env
   ```

3. **Add proxy config (choose one):**
   ```bash
   cat setup/env-templates/.env.proxy-traefik.template >> .env
   # OR
   cat setup/env-templates/.env.proxy-none.template >> .env
   ```

4. **Edit values in `.env`** to match your setup

## Adding New Templates

To add support for a new database or proxy:

1. Create new template file(s) in this directory
2. Update `interactive-scripts/setup.sh` to include new options
3. Update documentation

Example for adding MongoDB:
```bash
# Create templates
.env.mongodb-local.template
.env.mongodb-external.template

# Update setup.sh to concatenate them based on user choice
```

## Template Variables

All templates use `${VARIABLE}` syntax for environment variable substitution. These are replaced by Docker Compose when deploying the stack.

Common variables:
- `${IMAGE_NAME}` - Docker image name
- `${IMAGE_VERSION}` - Docker image version
- `${STACK_NAME}` - Docker stack name
- `${DATA_ROOT}` - Path for persistent data
- `${PORT}` - API port
- `${API_URL}` - Domain for Traefik routing
- `${PUBLISHED_PORT}` - Port for direct exposure

## Security Notes

- **Local database**: Password stored in Docker secrets (not in .env)
- **External database**: Password stored in .env (ensure .env is in .gitignore)
- Never commit `.env` files with real credentials to version control
