# Testing the Setup Wizard

## Quick Test

To verify the setup wizard generates correct swarm-stack.yml files:

```bash
# Run automated tests
cd testing
sh test-build.sh
```

**Expected Output:**
```
🧪 Testing swarm-stack.yml generation...
========================================

Test 1: PostgreSQL Local + Traefik
-----------------------------------
✅ PASSED: No placeholders found
✅ PASSED: Traefik labels found
✅ PASSED: No ports section found

Test 1: ✅ PASSED

Test 2: PostgreSQL Local + Direct Port
---------------------------------------
✅ PASSED: No placeholders found
✅ PASSED: Ports section found
✅ PASSED: No Traefik labels found

Test 2: ✅ PASSED

========================================
✅ All tests passed!
```

## Validate Your Generated Stack

After running the setup wizard:

```bash
# Linux/Mac
cd testing
./validate-stack.sh ../swarm-stack.yml

# Windows
cd testing
.\validate-stack.ps1 ..\swarm-stack.yml
```

## Compare with Examples

```bash
# View example files
ls testing/examples/

# Compare your file
diff swarm-stack.yml testing/examples/swarm-stack-traefik-postgres-local.yml
```

## Full Documentation

See `testing/README.md` for complete testing documentation including:
- Detailed test scenarios
- Validation procedures
- Troubleshooting guide
- Example files

## What Gets Tested

✅ Template injection works correctly  
✅ No unreplaced placeholders (`###PLACEHOLDER###`)  
✅ Traefik labels appear when Traefik is selected  
✅ Port mappings appear when direct port is selected  
✅ Database environment variables are injected  
✅ Valid YAML structure  

## Test Results

**Latest Run:** ✅ All tests passed

The fix ensures:
- Traefik labels correctly injected at `###PROXY_LABELS###`
- Port mappings correctly injected at `###PROXY_PORTS###`
- Unused placeholders are removed
- No conflicts between proxy configurations
