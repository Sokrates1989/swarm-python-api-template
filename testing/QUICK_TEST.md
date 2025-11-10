# Quick Test Guide

## Run Automated Tests

```bash
cd testing
sh test-build.sh
```

**Expected:** ✅ All tests passed!

## Validate Your Stack File

After running `./setup-wizard.sh` or `.\setup-wizard.ps1`:

```bash
# Linux/Mac
cd testing
./validate-stack.sh ../swarm-stack.yml

# Windows
cd testing
.\validate-stack.ps1 ..\swarm-stack.yml
```

## What Was Fixed

✅ Traefik labels now appear in swarm-stack.yml  
✅ Port mappings now appear for direct mode  
✅ No unreplaced `###PLACEHOLDER###` remain  

## Full Documentation

- **Testing:** See `testing/README.md`
- **Scenarios:** See `testing/TESTING_SCENARIOS.md`
- **Examples:** See `testing/examples/`
- **Summary:** See `testing/SUMMARY.md`
