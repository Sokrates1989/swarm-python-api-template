# swarm-python-api-template
Python API Template for Docker Swarm

This repository provides Docker Swarm deployment configuration for the Python API Template.

## Prerequisites

Before starting the deployment, ensure you have:

1. **Docker Swarm initialized** on your server
2. **Bash shell** (Linux/Mac: pre-installed, Windows: use Git Bash or WSL)
3. **A subdomain/domain** pointing to your swarm manager (see [Domain Setup](#domain-setup) below) - Only required if using Traefik proxy
4. **Repository cloned** to your server (see [Clone Repository](#clone-repository) below)

### Domain Setup

You need to create a subdomain (e.g., `api.example.com`) that points to your Docker Swarm manager's IP address.

#### For Strato Customers

1. Log in to your Strato account at [https://www.strato.de](https://www.strato.de)
2. Navigate to **Domains** → Select your domain
3. Click on **Domain Settings** → **Subdomain Management**
4. Click **Create New Subdomain**
5. Enter your subdomain name (e.g., `api`)
6. Set the **A Record** to point to your server's IP address
7. Save the settings
8. Wait 15-60 minutes for DNS propagation

#### For IONOS Customers

1. Log in to your IONOS account at [https://www.ionos.com](https://www.ionos.com)
2. Go to **Domains & SSL** → Select your domain
3. Click on **DNS Settings** or **Manage DNS**
4. Click **Add Record**
5. Select **A Record**
6. Enter your subdomain (e.g., `api`)
7. Enter your server's IP address
8. Set TTL to 3600 (or leave default)
9. Save the record
10. Wait 15-60 minutes for DNS propagation

**Note:** DNS propagation can take anywhere from a few minutes to 24 hours, but typically completes within an hour.

### Clone Repository

Choose an appropriate location on your server to clone the repository. For multi-node swarms, use a shared filesystem like GlusterFS.

```bash
# Recommended: Use shared storage for multi-node swarms
mkdir -p /gluster_storage/swarm/python-api-template
cd /gluster_storage/swarm/python-api-template

# Clone the repository
git clone https://github.com/Sokrates1989/swarm-python-api-template.git .

# Alternative: For single-node setups, you can use any directory
# mkdir -p /opt/swarm/python-api-template
# cd /opt/swarm/python-api-template
# git clone https://github.com/Sokrates1989/swarm-python-api-template.git .
```

## Quick Start (Recommended)

Once you have completed the prerequisites above, the easiest way to set up your deployment is using the interactive setup wizard:

### Linux/Mac
```bash
# Make the script executable
chmod +x setup/setup-wizard.sh

# Run the setup wizard
./setup/setup-wizard.sh
```

### Windows (PowerShell)
```powershell
# Run the setup wizard
.\setup\setup-wizard.ps1

# Alternative: If execution policy blocks it
powershell -ExecutionPolicy Bypass -File .\setup\setup-wizard.ps1
```

The setup wizard will:
1. Check for existing setup and create backups
2. Guide you through database selection (PostgreSQL or Neo4j)
3. Guide you through database mode (local or external)
4. Guide you through proxy selection (Traefik or no-proxy)
5. Build configuration files (`.env` and `swarm-stack.yml`)
6. Collect deployment parameters (stack name, image, replicas, etc.)
7. Guide you through Docker secret creation
8. Verify network configuration (for Traefik)
9. Create required data directories
10. Deploy the stack to Docker Swarm
11. Perform health checks on deployed services

### Modular Architecture

The new setup wizard uses a **modular architecture** for better maintainability:

- **`setup/modules/user-prompts`** - Handles all user input
- **`setup/modules/config-builder`** - Builds configuration files
- **`setup/modules/network-check`** - Verifies DNS for Traefik
- **`setup/modules/data-dirs`** - Creates data directories
- **`setup/modules/secret-manager`** - Manages Docker secrets
- **`setup/modules/deploy-stack`** - Deploys and health checks

See `setup/modules/README.md` for detailed module documentation.

## Proxy Options

The template supports two proxy configurations:

### 1. Traefik (Recommended)
- Automatic HTTPS with Let's Encrypt
- Domain-based routing
- Requires a domain pointing to your swarm manager
- Best for production deployments

### 2. No Proxy (Direct Port Exposure)
- Direct port mapping to host
- You manage your own reverse proxy/load balancer
- Useful for custom setups or when using other proxies (nginx, HAProxy, etc.)
- API accessible via `http://<server-ip>:<port>`

---

# Manual Setup (Alternative)

If you prefer to configure everything manually, follow these steps.

**Important:** Make sure you have completed the [Prerequisites](#prerequisites) section above (domain setup and repository cloning) before proceeding.

## Modular Configuration

This template uses a modular approach with Docker Compose includes. Instead of maintaining multiple complete template files, we combine smaller modules based on your choices:

- **Base modules**: Common configuration (Redis, networks, secrets)
- **Database modules**: PostgreSQL or Neo4j, local or external
- **Proxy modules**: Traefik or direct port exposure

The setup wizard automatically combines the right modules for your configuration.

### Manual Configuration

If you prefer manual setup, you'll need to:

1. **Build your .env file** by combining templates:
   ```bash
   # Start with base
   cat setup/env-templates/.env.base.template > .env
   
   # Add database config (choose one)
   cat setup/env-templates/.env.postgres-local.template >> .env    # PostgreSQL local
   cat setup/env-templates/.env.postgres-external.template >> .env # PostgreSQL external
   cat setup/env-templates/.env.neo4j-local.template >> .env       # Neo4j local
   cat setup/env-templates/.env.neo4j-external.template >> .env    # Neo4j external
   
   # Add proxy config (choose one)
   cat setup/env-templates/.env.proxy-traefik.template >> .env     # Traefik
   cat setup/env-templates/.env.proxy-none.template >> .env        # No proxy
   ```

2. **Create swarm-stack.yml** from template:
   ```bash
   cp setup/swarm-stack.yml.template swarm-stack.yml
   
   # Edit to include your chosen modules
   # Replace XXX_DATABASE_MODULE_XXX with:
   #   - postgres-local.yml or postgres-external.yml
   #   - neo4j-local.yml or neo4j-external.yml
   # Replace XXX_PROXY_MODULE_XXX with:
   #   - proxy-traefik.yml or proxy-none.yml
   ```

3. **Edit configuration values** in `.env`

See `setup/compose-modules/README.md` for details on the modular structure.

## Create secrets in docker swarm

### For PostgreSQL

```bash
# Database password secret
vi secret.txt  # Insert password (avoid backslashes "\") and save
docker secret create DB_PASSWORD_API_XXXXXXXXX secret.txt # Change name
rm secret.txt

# Admin API Key secret
vi secret.txt  # Insert admin API key and save
docker secret create ADMIN_API_KEY_API_XXXXXXXXX secret.txt # Change name
rm secret.txt
```

### For Neo4j

```bash
# Neo4j password secret
vi secret.txt  # Insert password (avoid backslashes "\") and save
docker secret create DB_PASSWORD_API_XXXXXXXXX secret.txt # Change name
rm secret.txt

# Admin API Key secret
vi secret.txt  # Insert admin API key and save
docker secret create ADMIN_API_KEY_API_XXXXXXXXX secret.txt # Change name
rm secret.txt
```

**Note**: 
- Redis password secret is optional for both configurations.
- For external database setups, you don't need to create a database password secret (password is in `.env`), but you still need the Admin API key secret.

## Edit configuration

### .env

```bash
# Edit the variables in .env.
vi .env
# Make a note of STACK_NAME, as you need it to replace <STACK_NAME>
# For Traefik setup: Configure API_URL with your domain
# For no-proxy setup: Configure PUBLISHED_PORT (default 8000)
# For external database: Configure DB_HOST, DB_PASSWORD, etc.
```

### swarm-stack.yml

```bash
# Edit the variables in swarm-stack.yml.
vi swarm-stack.yml

- Replace all occurrences of XXX_CHANGE_ME_DB_PASSWORD_XXX with the Secret name created before (DB_PASSWORD_API_XXXXXXXXX)
- Replace all occurrences of XXX_CHANGE_ME_ADMIN_API_KEY_XXX with the Secret name created before (ADMIN_API_KEY_API_XXXXXXXXX)
```

**Note**: The same secret names work for both PostgreSQL and Neo4j configurations.

# Deploy

```bash
# Deploy service on swarm using swarm-stack.yml
docker stack deploy -c swarm-stack.yml <STACK_NAME>
# WAIT till Readiness is confirmed as described below.
```

See [Determine Readiness](#determine-readiness) how to confirm readiness.

# Determine Readiness

```bash
# Check if there are any issues with initial deployment.
docker stack services <STACK_NAME>
# Make sure that the replicas numbers equal left and right side ( 1/1 is good. 0/1 is bad )

# In case of unequal replicas check issues of the service.
docker service ps <STACK_NAME>_api --no-trunc
docker service ps <STACK_NAME>_postgres --no-trunc  # For PostgreSQL
docker service ps <STACK_NAME>_neo4j --no-trunc     # For Neo4j
docker service ps <STACK_NAME>_redis --no-trunc

# If all replicas started properly, wait ~2 min then check logs.

# Desired log entry of API.
docker service logs <STACK_NAME>_api
# Should show: "Application startup complete" or similar

# Desired log entry of postgres (if using PostgreSQL).
docker service logs <STACK_NAME>_postgres
# Should show: "database system is ready to accept connections"

# Desired log entry of neo4j (if using Neo4j).
docker service logs <STACK_NAME>_neo4j
# Should show: "Started" or "Remote interface available"

# Desired log entry of redis.
docker service logs <STACK_NAME>_redis
# Should show: "Ready to accept connections"

# Test the API
curl https://api.example.com/health
# Should return: {"status":"healthy"}
```

# Re-Deploy to fix errors

## Backup database

### PostgreSQL Backup

```bash
# Connect to the database service
docker exec -it $(docker ps -q -f name=<STACK_NAME>_postgres) bash

# Inside the container, create a backup
pg_dump -U <DB_USER> <DB_NAME> > /tmp/backup.sql

# Exit and copy backup to host
docker cp $(docker ps -q -f name=<STACK_NAME>_postgres):/tmp/backup.sql ./backup.sql
```

### Neo4j Backup

```bash
# Neo4j data is stored in volumes at ${DATA_ROOT}/neo4j_data
# For backup, you can:
# 1. Stop the service
docker service scale <STACK_NAME>_neo4j=0

# 2. Copy the data directory
cp -r ${DATA_ROOT}/neo4j_data ${DATA_ROOT}/neo4j_data_backup_$(date +%Y%m%d)

# 3. Restart the service
docker service scale <STACK_NAME>_neo4j=1

# Or use Neo4j's built-in backup tools:
# https://neo4j.com/docs/operations-manual/current/backup-restore/
```

## Actual re-deployment

```bash
# Remove all services in the stack.
docker stack rm <STACK_NAME>

# Wait for all services to be removed
docker stack ps <STACK_NAME>  # Should show "no such stack"

# Re-deploy.
docker stack deploy -c swarm-stack.yml <STACK_NAME>
```

# Update API Image

```bash
# Pull the latest image
docker pull <IMAGE_NAME>:<IMAGE_VERSION>

# Update the service
docker service update --image <IMAGE_NAME>:<IMAGE_VERSION> <STACK_NAME>_api

# Or re-deploy the entire stack
docker stack deploy -c swarm-stack.yml <STACK_NAME>
```

# Access Database

## PostgreSQL Access

### Option 1: Using psql from host

```bash
# Connect to PostgreSQL service
docker exec -it $(docker ps -q -f name=<STACK_NAME>_postgres) psql -U <DB_USER> -d <DB_NAME>
```

### Option 2: Deploy pgAdmin (optional)

Add pgAdmin service to swarm-stack.yml and re-deploy.

## Neo4j Access

### Option 1: Using cypher-shell from host

```bash
# Connect to Neo4j service
docker exec -it $(docker ps -q -f name=<STACK_NAME>_neo4j) cypher-shell -u neo4j -p <PASSWORD>
```

### Option 2: Neo4j Browser (Web UI)

Neo4j Browser is available at port 7474. You can expose it via Traefik by adding labels to the neo4j service in swarm-stack.yml (only for Traefik setup):

```yaml
deploy:
  labels:
    - traefik.enable=true
    - traefik.http.services.${STACK_NAME}_neo4j.loadbalancer.server.port=7474
    - traefik.http.routers.${STACK_NAME}_neo4j.rule=Host(`neo4j.example.com`)
    - traefik.http.routers.${STACK_NAME}_neo4j.entrypoints=https
    - traefik.http.routers.${STACK_NAME}_neo4j.tls=true
    - traefik.http.routers.${STACK_NAME}_neo4j.tls.certresolver=le
```

# Scaling

```bash
# Scale API service
docker service scale <STACK_NAME>_api=3

# Or update .env and re-deploy
vi .env  # Set API_REPLICAS=3
docker stack deploy -c swarm-stack.yml <STACK_NAME>
```

# Monitoring

```bash
# View service status
docker stack services <STACK_NAME>

# View service logs
docker service logs -f <STACK_NAME>_api
docker service logs -f <STACK_NAME>_postgres
docker service logs -f <STACK_NAME>_redis

# View resource usage
docker stats
```

# Troubleshooting

## Service not starting

```bash
# Check service tasks
docker service ps <STACK_NAME>_api --no-trunc

# Check logs
docker service logs <STACK_NAME>_api

# Inspect service
docker service inspect <STACK_NAME>_api
```

## Database connection issues

### PostgreSQL

```bash
# Verify database service is running
docker service ps <STACK_NAME>_postgres

# Check database logs
docker service logs <STACK_NAME>_postgres

# Verify secrets are mounted correctly
docker exec -it $(docker ps -q -f name=<STACK_NAME>_api) ls -la /run/secrets/
```

### Neo4j

```bash
# Verify database service is running
docker service ps <STACK_NAME>_neo4j

# Check database logs
docker service logs <STACK_NAME>_neo4j

# Verify Neo4j is accepting connections
docker exec -it $(docker ps -q -f name=<STACK_NAME>_neo4j) cypher-shell -u neo4j -p <PASSWORD> "RETURN 1"

# Verify secrets are mounted correctly
docker exec -it $(docker ps -q -f name=<STACK_NAME>_api) ls -la /run/secrets/
```

## Network issues

```bash
# List networks
docker network ls

# Inspect backend network
docker network inspect <STACK_NAME>_backend

# Verify Traefik network exists
docker network inspect traefik
```
