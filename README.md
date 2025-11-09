# swarm-python-api-template
Python API Template for Docker Swarm

This repository provides Docker Swarm deployment configuration for the Python API Template.

## Prerequisites

Before starting the deployment, ensure you have:

1. **Docker Swarm initialized** on your server
2. **A subdomain/domain** pointing to your swarm manager (see [Domain Setup](#domain-setup) below)
3. **Repository cloned** to your server (see [Clone Repository](#clone-repository) below)

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

Once you have completed the prerequisites above, the easiest way to set up your deployment is using the quick-start scripts:

### Linux/Mac
```bash
./quick-start.sh
```

### Windows (PowerShell)
```powershell
.\quick-start.ps1
```

The quick-start script will:
1. Check Docker installation
2. Run an interactive setup wizard (first time only)
3. Guide you through database selection (PostgreSQL or Neo4j)
4. Configure local or external database mode
5. Help you deploy and manage your swarm stack

After running the setup wizard, you can use the quick-start script to:
- Deploy to Docker Swarm
- Check deployment status
- View service logs
- Update API images
- Scale services
- Create Docker secrets

---

# Manual Setup (Alternative)

If you prefer to configure everything manually, follow these steps.

**Important:** Make sure you have completed the [Prerequisites](#prerequisites) section above (domain setup and repository cloning) before proceeding.

## Copy templates

### For PostgreSQL (default)

```bash
# Copy ".env.postgres.template" to ".env".
cp setup/.env.postgres.template .env

# Copy "docker-compose.postgres.yml.template" to "docker-compose.yml".
cp setup/docker-compose.postgres.yml.template docker-compose.yml
```

### For Neo4j

```bash
# Copy ".env.neo4j.template" to ".env".
cp setup/.env.neo4j.template .env

# Copy "docker-compose.neo4j.yml.template" to "docker-compose.yml".
cp setup/docker-compose.neo4j.yml.template docker-compose.yml
```

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

**Note**: Redis password secret is optional for both configurations.

## Edit configuration

### .env

```bash
# Edit the variables in .env.
vi .env
# Make a note of STACK_NAME, as you need it to replace <STACK_NAME>
```

### docker-compose.yml

```bash
# Edit the variables in docker-compose.yml.
vi docker-compose.yml

- Replace all occurrences of XXX_CHANGE_ME_DB_PASSWORD_XXX with the Secret name created before (DB_PASSWORD_API_XXXXXXXXX)
- Replace all occurrences of XXX_CHANGE_ME_ADMIN_API_KEY_XXX with the Secret name created before (ADMIN_API_KEY_API_XXXXXXXXX)
```

**Note**: The same secret names work for both PostgreSQL and Neo4j configurations.

# Deploy

```bash
# Deploy service on swarm using .env via docker compose.
# https://github.com/moby/moby/issues/29133.
docker stack deploy -c <(docker-compose config) <STACK_NAME>
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
docker stack deploy -c <(docker-compose config) <STACK_NAME>
```

# Update API Image

```bash
# Pull the latest image
docker pull <IMAGE_NAME>:<IMAGE_VERSION>

# Update the service
docker service update --image <IMAGE_NAME>:<IMAGE_VERSION> <STACK_NAME>_api

# Or re-deploy the entire stack
docker stack deploy -c <(docker-compose config) <STACK_NAME>
```

# Access Database

## PostgreSQL Access

### Option 1: Using psql from host

```bash
# Connect to PostgreSQL service
docker exec -it $(docker ps -q -f name=<STACK_NAME>_postgres) psql -U <DB_USER> -d <DB_NAME>
```

### Option 2: Deploy pgAdmin (optional)

Add pgAdmin service to docker-compose.yml and re-deploy.

## Neo4j Access

### Option 1: Using cypher-shell from host

```bash
# Connect to Neo4j service
docker exec -it $(docker ps -q -f name=<STACK_NAME>_neo4j) cypher-shell -u neo4j -p <PASSWORD>
```

### Option 2: Neo4j Browser (Web UI)

Neo4j Browser is available at port 7474. You can expose it via Traefik by adding labels to the neo4j service in docker-compose.yml:

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
docker stack deploy -c <(docker-compose config) <STACK_NAME>
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
