# Compose Modules

This directory contains modular Docker Compose files that are combined to create your final swarm stack configuration.

## Module Structure

### Base Modules (Always Included)

- **`base.yml`** - Common services (Redis) and base configuration
- **`api-base.yml`** - Base API service configuration

### Database Modules (Choose One)

#### Local Database (Database deployed in swarm)
- **`postgres-local.yml`** - PostgreSQL database service + API database config
- **`neo4j-local.yml`** - Neo4j database service + API database config

#### External Database (Connect to existing database)
- **`postgres-external.yml`** - API configuration for external PostgreSQL
- **`neo4j-external.yml`** - API configuration for external Neo4j

### Proxy Modules (Choose One)

- **`proxy-traefik.yml`** - Traefik labels and network for automatic HTTPS
- **`proxy-none.yml`** - Direct port exposure (no proxy)

## How It Works

The setup wizard combines these modules based on your choices:

```yaml
# Example: PostgreSQL local + Traefik
include:
  - compose-modules/base.yml
  - compose-modules/api-base.yml
  - compose-modules/postgres-local.yml
  - compose-modules/proxy-traefik.yml
```

```yaml
# Example: Neo4j external + No proxy
include:
  - compose-modules/base.yml
  - compose-modules/api-base.yml
  - compose-modules/neo4j-external.yml
  - compose-modules/proxy-none.yml
```

## Benefits

1. **No Redundancy** - Each configuration option is defined once
2. **Easy Maintenance** - Update one file to affect all combinations
3. **Clear Separation** - Database, proxy, and base configs are separate
4. **Flexible** - Easy to add new database types or proxy options

## Adding New Modules

To add a new database type (e.g., MongoDB):

1. Create `mongodb-local.yml` and `mongodb-external.yml`
2. Update `setup.sh` to include MongoDB as an option
3. Add corresponding `.env` templates

To add a new proxy type (e.g., nginx):

1. Create `proxy-nginx.yml`
2. Update `setup.sh` to include nginx as an option
3. Add corresponding `.env` template
