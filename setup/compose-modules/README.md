# Compose Modules

This directory contains modular Docker Compose files and snippets that are combined to create your final swarm stack configuration.

## Module Structure

### Core Files

- **`base.yml`** - Base structure with `services:` key and Redis service
- **`api.template.yml`** - API service template with placeholder markers
- **`footer.yml`** - Networks and secrets definitions (always last)

### Database Service Modules (For Local Deployment)

- **`postgres-local.yml`** - PostgreSQL database service definition
- **`neo4j-local.yml`** - Neo4j database service definition
- **`postgres-external.yml`** - Empty (external databases don't need service definitions)
- **`neo4j-external.yml`** - Empty (external databases don't need service definitions)

### Snippets Directory

Small, focused configuration snippets that get injected into the API template:

#### Database Environment Snippets (`snippets/`)
- **`db-postgresql-local.env.yml`** - PostgreSQL local connection environment variables
- **`db-postgresql-external.env.yml`** - PostgreSQL external connection environment variables
- **`db-neo4j-local.env.yml`** - Neo4j local connection environment variables
- **`db-neo4j-external.env.yml`** - Neo4j external connection environment variables

#### Proxy Configuration Snippets (`snippets/`)
- **`proxy-traefik.network.yml`** - Traefik network addition for API service
- **`proxy-traefik.labels.yml`** - Traefik deployment labels for automatic HTTPS
- **`proxy-none.ports.yml`** - Direct port mapping (no proxy)

## How It Works

The setup wizard uses a **template injection** approach:

1. **Start with base structure**
   ```bash
   cat base.yml > swarm-stack.yml
   # Contains: services: + redis service
   ```

2. **Build API service from template**
   ```bash
   cp api.template.yml temp.yml
   # Inject database environment snippet into ###DATABASE_ENV###
   # Inject proxy network into ###PROXY_NETWORK### (if Traefik)
   # Inject proxy config into ###PROXY_PORTS### or ###PROXY_LABELS###
   cat temp.yml >> swarm-stack.yml
   ```

3. **Add database service (if local)**
   ```bash
   cat postgres-local.yml >> swarm-stack.yml  # Only if local deployment
   ```

4. **Close with footer**
   ```bash
   cat footer.yml >> swarm-stack.yml
   # Contains: networks: + secrets:
   ```

### Example: PostgreSQL Local + Traefik

```
base.yml (services: + redis)
  + api.template.yml with:
    - db-postgresql-local.env.yml injected
    - proxy-traefik.network.yml injected
    - proxy-traefik.labels.yml injected
  + postgres-local.yml (postgres service)
  + footer.yml (networks: + secrets:)
= Valid swarm-stack.yml
```

## Benefits

1. **Single Source of Truth** - API configuration in one template file
2. **No Duplicate Keys** - Proper YAML structure with single `services:`, `networks:`, `secrets:` keys
3. **Easy Maintenance** - Change API once, affects all configurations
4. **Small Snippets** - Focused, reusable configuration pieces
5. **Flexible** - Easy to add new database types or proxy options

## Adding New Modules

### To add a new database type (e.g., MongoDB):

1. Create database environment snippets:
   - `snippets/db-mongodb-local.env.yml`
   - `snippets/db-mongodb-external.env.yml`

2. Create database service module:
   - `mongodb-local.yml` (with MongoDB service definition)
   - `mongodb-external.yml` (empty file)

3. Update setup wizard scripts to include MongoDB as an option

4. Add corresponding `.env` templates in `setup/env-templates/`

### To add a new proxy type (e.g., nginx):

1. Create proxy snippets:
   - `snippets/proxy-nginx.network.yml` (if needed)
   - `snippets/proxy-nginx.labels.yml` or `snippets/proxy-nginx.ports.yml`

2. Update setup wizard scripts to include nginx as an option

3. Add corresponding `.env` template

## File Naming Convention

- **Modules**: `{type}-{mode}.yml` (e.g., `postgres-local.yml`)
- **Snippets**: `{category}-{type}-{mode}.{section}.yml` (e.g., `db-postgresql-local.env.yml`)
- **Template**: `{service}.template.yml` (e.g., `api.template.yml`)
