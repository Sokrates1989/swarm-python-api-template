# Multi-Site Deployment Plan for Swarm Python API Template

## Overview

This plan implements **multi-site deployment** for the Swarm Python API Template, starting with PostgreSQL support, then adding MongoDB.

**Approach:**
1. **Phase 1:** Multi-site foundation (PostgreSQL only) - TESTABLE
2. **Phase 2:** MongoDB database support - TESTABLE
3. **Phase 3:** Operations (backup, monitoring) per site - TESTABLE

---

## Phase 1: Multi-Site Foundation (PostgreSQL Only)

### 1.1 Site Configuration Structure

**New Directory:**
```
site-configs/                      # Site configuration storage
├── api-demo.json                # Example: Demo site
├── api-staging.json             # Example: Staging site
└── _template.json               # Template for new sites
```

**Site Config Schema (PostgreSQL first):**
```json
{
  "siteId": "api-demo",
  "name": "Demo API",
  "description": "Demo API for testing",
  "domain": "api-demo.example.com",
  "database": {
    "type": "postgresql",
    "mode": "local"
  },
  "proxy": {
    "type": "traefik",
    "ssl": true
  },
  "ports": {
    "api": 8080,
    "postgres": 5432,
    "pgAdmin": 5050
  },
  "resources": {
    "apiReplicas": 2,
    "memoryLimit": "512M"
  },
  "backendAppId": "demo_app",
  "envOverrides": {}
}
```

### 1.2 Site-Specific Deployment Folders

**New Directory Structure:**
```
deployments/                       # All site deployments
├── _base/                        # Shared base configurations
│   ├── base.yml                  # Base compose (networks, secrets)
│   ├── redis.yml                 # Shared Redis service
│   └── traefik.yml               # Traefik proxy (shared)
├── api-demo/                     # Site: api-demo
│   ├── .env                      # Site-specific environment
│   ├── swarm-stack.yml           # Generated stack file
│   ├── compose.override.yml      # Local overrides
│   └── data/                     # Site data
│       ├── postgres/             # PostgreSQL data
│       └── redis/                # Redis data
└── api-staging/                  # Site: api-staging
    ├── .env
    ├── swarm-stack.yml
    └── data/
        └── postgres/
```

### 1.3 Compose Module Refactoring

**Current:** `setup/compose-modules/`

**Refactored:**
```
setup/compose-modules/
├── base.yml                      # Networks, secrets (shared)
├── redis.yml                     # Redis service (shared)
├── api.template.yml              # API service template
├── postgres/
│   ├── local.yml                 # PostgreSQL container
│   └── external.yml              # External PostgreSQL config
└── proxy/
    ├── traefik.yml               # Traefik proxy
    └── none.yml                  # No proxy (direct ports)
```

### 1.4 Quick-Start Site Management

**Modified:** `quick-start.ps1` and `quick-start.sh`

**New Menu - Site Selection:**
```
========================================
  Swarm Python API - Site Management
========================================

Deployed Sites:
  1) api-demo (PostgreSQL, api-demo.example.com)
  2) api-staging (PostgreSQL, api-staging.example.com)

Options:
  n) Create New Site
  d) Delete Site
  s) Switch Active Site
  
Select [1-2, n, d, s]: 
```

**New Site Wizard:**
1. Enter site ID (e.g., `api-demo`)
2. Enter site name (e.g., `Demo API`)
3. Enter domain (e.g., `api-demo.example.com`)
4. Select database mode:
   - Local PostgreSQL (container)
   - External PostgreSQL
5. Configure ports
6. Select backend app ID from `app/apps/`
7. Generate site config and deployment files

### 1.5 Config Builder Site Support

**Modified:** `setup/modules/config-builder.ps1`

**Logic:**
```powershell
function Build-SiteStack {
    param($SiteId)
    
    $config = Get-Content "site-configs/${SiteId}.json" | ConvertFrom-Json
    
    # Compose files to include:
    $composeFiles = @(
        "deployments/_base/base.yml",
        "deployments/_base/redis.yml"
    )
    
    # Add database module
    switch ($config.database.type) {
        "postgresql" {
            if ($config.database.mode -eq "local") {
                $composeFiles += "setup/compose-modules/postgres/local.yml"
            }
        }
        # Placeholder for MongoDB (Phase 2)
        "mongodb" { 
            Write-Error "MongoDB not yet implemented (Phase 2)"
        }
    }
    
    # Add proxy module
    $composeFiles += "setup/compose-modules/proxy/$($config.proxy.type).yml"
    
    # Add API service (site-specific)
    $composeFiles += "deployments/${SiteId}/api.yml"
    
    # Generate swarm-stack.yml
    docker compose $(foreach($f in $composeFiles) { "-f", $f }) config `
        > "deployments/${SiteId}/swarm-stack.yml"
}
```

### 1.6 Environment File Generation

**New:** Site-specific `.env` generation

**Template Variables:**
```bash
# Site Identity
SITE_ID=api-demo
SITE_NAME=Demo API
DOMAIN=api-demo.example.com

# Backend App
BACKEND_APP_ID=demo_app

# Database (PostgreSQL)
DB_TYPE=postgresql
DB_MODE=local
POSTGRES_HOST=postgres-api-demo
POSTGRES_PORT=5432
POSTGRES_DB=api_demo_db
POSTGRES_USER=api_user
POSTGRES_PASSWORD_FILE=/run/secrets/api-demo_postgres_password

# Ports
API_PORT=8080
PGADMIN_PORT=5050

# Data Directories (site-specific)
DATA_DIR=/deployments/api-demo/data
POSTGRES_DATA_DIR=/deployments/api-demo/data/postgres

# Traefik Labels (site-specific)
TRAEFIK_ROUTER_NAME=api-demo
TRAEFIK_RULE=Host(`api-demo.example.com`)
```

### 1.7 Data Directory Management

**Modified:** `setup/modules/data-dirs.ps1`

**Site-Aware Functions:**
```powershell
function Initialize-SiteDataDirs {
    param($SiteId)
    
    $dirs = @(
        "deployments/${SiteId}/data/postgres",
        "deployments/${SiteId}/data/redis",
        "deployments/${SiteId}/data/logs"
    )
    
    foreach ($dir in $dirs) {
        New-Item -ItemType Directory -Force -Path $dir
    }
}
```

### 1.8 Secrets Management (Site-Specific)

**Modified:** `setup/modules/secret-manager.ps1`

**Site-Secret Naming:** `{siteId}_{secretName}`

Example secrets:
- `api-demo_postgres_password`
- `api-demo_jwt_secret`
- `api-demo_api_key`

---

## Phase 1 Testing Checklist

Before proceeding to Phase 2, verify:

- [ ] Can create new site via wizard
- [ ] Can deploy multiple PostgreSQL sites simultaneously
- [ ] Each site has isolated data directories
- [ ] Can switch between sites in quick-start
- [ ] Can delete site (removes data, secrets, config)
- [ ] Site-specific secrets work correctly
- [ ] Traefik routes correctly per domain
- [ ] Port allocation works (no conflicts)
- [ ] `deployments/{siteId}/swarm-stack.yml` generates correctly

---

## Phase 2: MongoDB Support (After Phase 1 Works)

### 2.1 MongoDB Compose Modules

**New Files:**
```
setup/compose-modules/mongodb/
├── local.yml                     # MongoDB container
└── external.yml                  # External MongoDB config
```

### 2.2 MongoDB Environment Templates

**New:**
```
setup/env-templates/
└── mongodb-local.env.template
```

Variables:
```bash
DB_TYPE=mongodb
MONGODB_HOST=mongodb-${SITE_ID}
MONGODB_PORT=27017
MONGODB_DATABASE=${SITE_ID}_db
MONGODB_URI=mongodb://.../
```

### 2.3 Update Config Builder

**Modified:** `setup/modules/config-builder.ps1`

**Add:**
```powershell
"mongodb" {
    if ($config.database.mode -eq "local") {
        $composeFiles += "setup/compose-modules/mongodb/local.yml"
    } else {
        $composeFiles += "setup/compose-modules/mongodb/external.yml"
    }
}
```

### 2.4 Update Data Dirs

**Modified:** `setup/modules/data-dirs.ps1`

**Add:**
```powershell
"deployments/${SiteId}/data/mongodb"
```

### 2.5 Update Secrets

**Add MongoDB secrets:**
- `{siteId}_mongodb_root_password`
- `{siteId}_mongodb_app_password`

---

## Phase 3: Operations Per Site

### 3.1 Site-Aware Health Checks

**Modified:** `setup/modules/health-check.ps1`

```powershell
function Test-SiteHealth {
    param($SiteId)
    
    $config = Get-Content "site-configs/${SiteId}.json" | ConvertFrom-Json
    
    # Check API
    Test-ApiHealth -Port $config.ports.api
    
    # Check Database (type-specific)
    switch ($config.database.type) {
        "postgresql" { Test-PostgresHealth -SiteId $SiteId }
        "mongodb" { Test-MongoDbHealth -SiteId $SiteId }
    }
}
```

### 3.2 Site-Aware Backup/Restore

**New Scripts:**
- `scripts/backup-site.sh/ps1` - Backup specific site
- `scripts/restore-site.sh/ps1` - Restore specific site
- `scripts/backup-all.sh/ps1` - Backup all sites

---

## Implementation Order (Revised)

### Phase 1A: Core Multi-Site (PostgreSQL Only)
1. Create `site-configs/` directory with JSON schema
2. Create `deployments/` directory structure
3. Create example site configs (api-demo, api-staging)
4. **TEST:** Verify directory structure

### Phase 1B: Config Builder
1. Refactor compose modules to `postgres/` subdirectory
2. Update `config-builder.ps1` to read site config
3. Generate site-specific `swarm-stack.yml`
4. **TEST:** Generate stack files for demo sites

### Phase 1C: Quick-Start Integration
1. Add site selection menu
2. Add "Create New Site" wizard
3. Add "Delete Site" function
4. **TEST:** Create and delete sites

### Phase 1D: Data & Secrets
1. Update `data-dirs.ps1` for site-specific paths
2. Update `secret-manager.ps1` for site-specific secrets
3. **TEST:** Deploy multiple sites, verify isolation

### Phase 1E: Polish
1. Health checks per site
2. Backup/restore per site
3. Documentation
4. **TEST:** Full multi-site deployment

### Phase 2: MongoDB (After Phase 1 Complete)
(See Phase 2 section above)

---

## Success Criteria (Phase 1 Only)

1. ✅ Can create 2+ PostgreSQL sites via wizard
2. ✅ Can deploy all sites to swarm simultaneously
3. ✅ Each site has isolated postgres data
4. ✅ Can switch active site in quick-start
5. ✅ Can delete site (cleanup complete)
6. ✅ Site-specific secrets work
7. ✅ Traefik routes per domain correctly
8. ✅ Health checks work per site

---

## Files to Modify/Create

### Phase 1A (Structure)
- [ ] `site-configs/_template.json`
- [ ] `site-configs/api-demo.json`
- [ ] `deployments/_base/base.yml`
- [ ] `deployments/_base/redis.yml`

### Phase 1B (Config Builder)
- [ ] Move: `postgres-local.yml` → `postgres/local.yml`
- [ ] Move: `postgres-external.yml` → `postgres/external.yml`
- [ ] Modify: `setup/modules/config-builder.ps1`

### Phase 1C (Quick-Start)
- [ ] Modify: `quick-start.ps1` - Site menu
- [ ] Modify: `quick-start.sh` - Site menu

### Phase 1D (Operations)
- [ ] Modify: `setup/modules/data-dirs.ps1`
- [ ] Modify: `setup/modules/secret-manager.ps1`

### Phase 1E (Health/Backup)
- [ ] Modify: `setup/modules/health-check.ps1`
- [ ] New: `scripts/backup-site.ps1`
- [ ] New: `scripts/restore-site.ps1`

---

## Next Steps

**Ready to start Phase 1A?**

1. Create `site-configs/` with example sites
2. Create `deployments/` base structure
3. Test JSON schema

**Commit point:** After Phase 1A completes, we have a testable foundation.
