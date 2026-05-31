# Multi-Site Deployment Guide

## Overview

The Swarm Python API Template now supports deploying **multiple independent API sites** from a single repository. Each site has:

- Isolated database (PostgreSQL)
- Isolated data directories
- Site-specific configuration
- Site-specific secrets
- Independent domain routing via Traefik

## Quick Start

### 1. Site Configuration

Sites are defined in `site-configs/` as JSON files:

```json
{
  "siteId": "api-demo",
  "name": "Demo API",
  "domain": "api-demo.example.com",
  "database": {
    "type": "postgresql",
    "mode": "local"
  },
  "ports": {
    "api": 8081,
    "postgres": 5433,
    "pgAdmin": 5051
  },
  "backendAppId": "demo_app"
}
```

### 2. Build Site Stack

```bash
# Build the Docker Swarm stack for a site
./scripts/build-site-stack.sh api-demo

# This generates: deployments/api-demo/swarm-stack.yml
```

### 3. Initialize Data Directories

```bash
# Create data directories for the site
./scripts/init-site-data.sh api-demo

# Creates: deployments/api-demo/data/postgres, redis, logs
```

### 4. Create Secrets

```bash
# Create site-specific Docker secrets
docker secret create api-demo_postgres_password <(openssl rand -base64 32)
docker secret create api-demo_jwt_secret <(openssl rand -base64 32)
docker secret create api-demo_pgadmin_password <(openssl rand -base64 32)
```

### 5. Deploy

```bash
# Deploy the stack to Docker Swarm
docker stack deploy -c deployments/api-demo/swarm-stack.yml api-demo
```

## Site Structure

```
swarm-python-api-template/
├── site-configs/              # Site definitions
│   ├── api-demo.json
│   └── api-staging.json
├── deployments/
│   ├── _base/                 # Shared infrastructure
│   │   ├── base.yml          # Networks, global secrets
│   │   └── traefik.yml       # Shared Traefik proxy
│   ├── api-demo/             # Site: api-demo
│   │   ├── .env              # Site environment
│   │   ├── api.yml           # API service
│   │   ├── postgres.yml      # PostgreSQL service
│   │   ├── swarm-stack.yml   # Generated stack
│   │   └── data/
│   │       ├── postgres/     # PostgreSQL data
│   │       └── redis/        # Redis data
│   └── api-staging/          # Site: api-staging
└── scripts/
    ├── build-site-stack.sh   # Build stack from config
    └── init-site-data.sh     # Init data directories
```

## Site Configuration Reference

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `siteId` | string | Unique site identifier (lowercase, no spaces) |
| `name` | string | Human-readable site name |
| `domain` | string | Domain for Traefik routing |
| `database.type` | string | Database type: `postgresql` (more coming) |
| `database.mode` | string | `local` (container) or `external` |
| `backendAppId` | string | Backend app ID from `app/apps/` |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `description` | string | - | Site description |
| `proxy.type` | string | `traefik` | Reverse proxy type |
| `proxy.ssl` | boolean | `true` | Enable SSL/TLS |
| `ports.api` | number | 8080 | API external port |
| `ports.postgres` | number | 5432 | PostgreSQL external port |
| `ports.pgAdmin` | number | 5050 | pgAdmin external port |
| `resources.apiReplicas` | number | 1 | API container replicas |
| `resources.memoryLimit` | string | `512M` | Memory limit per container |
| `envOverrides` | object | `{}` | Additional environment variables |

## Multiple Sites Example

### api-demo (Development)

```json
{
  "siteId": "api-demo",
  "name": "Demo API",
  "domain": "api-demo.example.com",
  "database": { "type": "postgresql", "mode": "local" },
  "ports": { "api": 8081, "postgres": 5433, "pgAdmin": 5051 },
  "resources": { "apiReplicas": 1, "memoryLimit": "512M" },
  "backendAppId": "demo_app",
  "envOverrides": { "DEBUG": "true" }
}
```

### api-staging (Staging)

```json
{
  "siteId": "api-staging",
  "name": "Staging API",
  "domain": "api-staging.example.com",
  "database": { "type": "postgresql", "mode": "local" },
  "ports": { "api": 8082, "postgres": 5434, "pgAdmin": 5052 },
  "resources": { "apiReplicas": 2, "memoryLimit": "1G" },
  "backendAppId": "template_app",
  "envOverrides": { "LOG_LEVEL": "debug" }
}
```

## Creating a New Site

### Step 1: Create Site Config

```bash
cp site-configs/_template.json site-configs/api-prod.json
# Edit api-prod.json with your values
```

### Step 2: Create Deployment Files

```bash
mkdir -p deployments/api-prod/data/postgres
mkdir -p deployments/api-prod/data/redis

# Copy and customize from existing site
cp deployments/api-demo/api.yml deployments/api-prod/api.yml
cp deployments/api-demo/postgres.yml deployments/api-prod/postgres.yml
cp deployments/api-demo/.env deployments/api-prod/.env

# Edit .env: Change all api-demo → api-prod
```

### Step 3: Build & Deploy

```bash
./scripts/build-site-stack.sh api-prod
./scripts/init-site-data.sh api-prod
# Create secrets...
docker stack deploy -c deployments/api-prod/swarm-stack.yml api-prod
```

## Site Management Commands

### List Sites

```bash
ls site-configs/*.json | xargs -I {} basename {} .json
```

### Delete Site

```bash
# 1. Remove stack
docker stack rm api-demo

# 2. Remove data (DANGER: permanent!)
rm -rf deployments/api-demo/data

# 3. Remove secrets
docker secret rm api-demo_postgres_password
# ... remove other secrets

# 4. Remove config
rm site-configs/api-demo.json
rm -rf deployments/api-demo
```

### Site Status

```bash
# Check stack status
docker stack ps api-demo
docker stack services api-demo

# Check logs
docker service logs api-demo_api
docker service logs api-demo_postgres
```

## Networking

### Shared Traefik

All sites use a shared Traefik instance (deployed from `deployments/_base/traefik.yml`):

- Routes traffic based on `Host()` rule
- Handles SSL/TLS certificates via Let's Encrypt
- Single entry point for all sites (ports 80/443)

### Isolated Backend Networks

Each site stack creates its own isolated backend network:
- Services within a site can communicate
- Sites cannot access each other's databases

## Data Isolation

Each site has completely isolated data:

```
deployments/
├── api-demo/
│   └── data/
│       ├── postgres/     # Site 1 database
│       └── redis/        # Site 1 cache
└── api-staging/
    └── data/
        ├── postgres/     # Site 2 database
        └── redis/        # Site 2 cache
```

## Secrets Management

Secrets are site-specific and prefixed with `{siteId}_`:

- `api-demo_postgres_password`
- `api-demo_jwt_secret`
- `api-staging_postgres_password`
- `api-staging_jwt_secret`

This ensures secrets from one site cannot be accessed by another.

## Troubleshooting

### Port Conflicts

Ensure each site has unique external ports:

```json
// api-demo: ports 8081, 5433, 5051
// api-staging: ports 8082, 5434, 5052
// api-prod: ports 8083, 5435, 5053
```

### Stack Build Fails

Check:
1. Site config JSON is valid
2. All referenced compose files exist
3. Docker is running
4. Environment file exists at `deployments/{siteId}/.env`

### Traefik Not Routing

Check:
1. Traefik is deployed: `docker stack ps traefik`
2. Site labels are correct in swarm-stack.yml
3. DNS points to swarm node
4. Certificates are valid

## Next Steps

1. **Test PostgreSQL sites**: Verify multi-site deployment works
2. **Add MongoDB support**: See Phase 2 in the plan
3. **Backup per site**: Implement site-specific backup scripts
4. **Monitoring**: Add site-aware health checks
