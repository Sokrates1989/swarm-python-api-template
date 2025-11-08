# Setup Templates

This directory contains template files for different database configurations.

## Files

### PostgreSQL Configuration
- `.env.postgres.template` - Environment variables for PostgreSQL setup
- `docker-compose.postgres.yml.template` - Docker Compose file with PostgreSQL service

### Neo4j Configuration
- `.env.neo4j.template` - Environment variables for Neo4j setup
- `docker-compose.neo4j.yml.template` - Docker Compose file with Neo4j service

## Usage

### Automated Setup (Recommended)
Run the quick-start script from the project root:
```bash
./quick-start.sh  # Linux/Mac
.\quick-start.ps1  # Windows
```

The interactive setup wizard will automatically select and configure the appropriate templates based on your choices.

### Manual Setup
If you prefer manual configuration:

1. Choose your database type (PostgreSQL or Neo4j)
2. Copy the appropriate templates to the project root:
   ```bash
   # For PostgreSQL
   cp setup/.env.postgres.template .env
   cp setup/docker-compose.postgres.yml.template docker-compose.yml
   
   # For Neo4j
   cp setup/.env.neo4j.template .env
   cp setup/docker-compose.neo4j.yml.template docker-compose.yml
   ```
3. Edit `.env` and `docker-compose.yml` to configure your deployment
4. Replace secret placeholders in `docker-compose.yml`
5. Create Docker secrets
6. Deploy to swarm

See the main README.md for detailed manual setup instructions.
