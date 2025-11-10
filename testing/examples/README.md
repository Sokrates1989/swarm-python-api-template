# Example swarm-stack.yml Files

This directory contains example output files showing what the correctly generated `swarm-stack.yml` should look like after running the setup wizard.

## Files

### `swarm-stack-traefik-postgres-local.yml`
**Configuration:**
- Database: PostgreSQL (Local)
- Proxy: Traefik

**Key Features:**
- ✅ Traefik labels under `deploy.labels` section
- ✅ Traefik network in `api` service networks
- ✅ PostgreSQL service included
- ✅ NO `ports:` section in api service (routing via Traefik)
- ✅ NO unreplaced placeholders

**Use Case:** Production deployment with automatic HTTPS via Traefik reverse proxy.

---

### `swarm-stack-direct-postgres-local.yml`
**Configuration:**
- Database: PostgreSQL (Local)
- Proxy: None (Direct Port Mapping)

**Key Features:**
- ✅ `ports:` section in api service for direct access
- ✅ PostgreSQL service included
- ✅ NO Traefik labels
- ✅ NO Traefik network
- ✅ NO unreplaced placeholders

**Use Case:** Development or testing with direct port access.

---

## How to Compare

After running the setup wizard, compare your generated `swarm-stack.yml` with these examples:

### Linux/Mac
```bash
# Run setup wizard
./setup-wizard.sh

# Compare with example
diff swarm-stack.yml examples/swarm-stack-traefik-postgres-local.yml
```

### Windows
```powershell
# Run setup wizard
.\setup-wizard.ps1

# Compare with example
Compare-Object (Get-Content swarm-stack.yml) (Get-Content examples\swarm-stack-traefik-postgres-local.yml)
```

## What to Look For

### ✅ Good Signs
- Clean YAML structure
- No `###PLACEHOLDER###` text
- Traefik labels present (if using Traefik)
- Ports present (if using direct mode)
- All environment variables defined

### ❌ Bad Signs
- `###PROXY_LABELS###` or `###PROXY_PORTS###` still present
- `###DATABASE_ENV###` still present
- `XXX_CHANGE_ME_` placeholders (should be replaced by wizard)
- Both Traefik labels AND ports (should be one or the other)

## Validation

Use the provided validation scripts to check your generated file:

```bash
# Linux/Mac
./validate-stack.sh

# Windows
.\validate-stack.ps1
```

## Notes

- These examples use placeholder environment variables (e.g., `${IMAGE_NAME}`) which are normal and will be evaluated at deployment time
- Secret names like `MYAPI_DB_PASSWORD` are examples - your actual secret names will be based on your stack name
- The Traefik network name (`traefik`) should match your actual Traefik network
