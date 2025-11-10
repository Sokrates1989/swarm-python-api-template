#!/bin/bash
# Validation script for swarm-stack.yml
# Tests that the generated stack file is correct and has no placeholders

set -e

STACK_FILE="${1:-swarm-stack.yml}"
ERRORS=0

echo "🔍 Validating $STACK_FILE..."
echo "================================"
echo ""

# Check if file exists
if [ ! -f "$STACK_FILE" ]; then
    echo "❌ ERROR: File $STACK_FILE not found"
    exit 1
fi

# Check for unreplaced placeholders
echo "1️⃣  Checking for unreplaced placeholders..."
if grep -q "###" "$STACK_FILE"; then
    echo "   ❌ ERROR: Found unreplaced placeholders:"
    grep -n "###" "$STACK_FILE" | while read -r line; do
        echo "      Line: $line"
    done
    ERRORS=$((ERRORS + 1))
else
    echo "   ✅ No placeholders found"
fi
echo ""

# Check for XXX_ placeholders that should have been replaced
echo "2️⃣  Checking for unreplaced XXX_ placeholders..."
UNREPLACED=$(grep -n "XXX_CHANGE_ME_" "$STACK_FILE" || true)
if [ -n "$UNREPLACED" ]; then
    echo "   ⚠️  WARNING: Found unreplaced XXX_ placeholders (this is OK before running wizard):"
    echo "$UNREPLACED" | head -5 | while read -r line; do
        echo "      $line"
    done
else
    echo "   ✅ All XXX_ placeholders replaced"
fi
echo ""

# Validate YAML syntax with docker (if available)
echo "3️⃣  Validating YAML syntax..."
if command -v docker &> /dev/null; then
    if docker stack config -c "$STACK_FILE" > /dev/null 2>&1; then
        echo "   ✅ Valid Docker Compose YAML syntax"
    else
        echo "   ❌ ERROR: Invalid YAML syntax"
        echo "      Run: docker stack config -c $STACK_FILE"
        ERRORS=$((ERRORS + 1))
    fi
else
    echo "   ⚠️  WARNING: Docker not found, skipping syntax validation"
fi
echo ""

# Check for common issues
echo "4️⃣  Checking structure..."

# Check for services key
if grep -q "^services:" "$STACK_FILE"; then
    echo "   ✅ Has 'services:' key"
else
    echo "   ❌ ERROR: Missing 'services:' key"
    ERRORS=$((ERRORS + 1))
fi

# Check for networks key
if grep -q "^networks:" "$STACK_FILE"; then
    echo "   ✅ Has 'networks:' key"
else
    echo "   ❌ ERROR: Missing 'networks:' key"
    ERRORS=$((ERRORS + 1))
fi

# Check for secrets key
if grep -q "^secrets:" "$STACK_FILE"; then
    echo "   ✅ Has 'secrets:' key"
else
    echo "   ❌ ERROR: Missing 'secrets:' key"
    ERRORS=$((ERRORS + 1))
fi

# Check for api service
if grep -q "^  api:" "$STACK_FILE"; then
    echo "   ✅ Has 'api' service"
else
    echo "   ❌ ERROR: Missing 'api' service"
    ERRORS=$((ERRORS + 1))
fi

# Check for redis service
if grep -q "^  redis:" "$STACK_FILE"; then
    echo "   ✅ Has 'redis' service"
else
    echo "   ❌ ERROR: Missing 'redis' service"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# Check proxy configuration
echo "5️⃣  Checking proxy configuration..."
if grep -q "traefik.enable=true" "$STACK_FILE"; then
    echo "   📡 Traefik proxy detected"
    
    # Check for required traefik labels
    REQUIRED_LABELS=(
        "traefik.enable=true"
        "traefik.constraint-label=traefik-public"
        "traefik.docker.network"
        "traefik.http.routers"
        "traefik.http.services"
    )
    
    for label in "${REQUIRED_LABELS[@]}"; do
        if grep -q "$label" "$STACK_FILE"; then
            echo "   ✅ Has label: $label"
        else
            echo "   ❌ ERROR: Missing label: $label"
            ERRORS=$((ERRORS + 1))
        fi
    done
    
    # Check that ports are NOT defined for api service
    if grep -A 50 "^  api:" "$STACK_FILE" | grep -q "^    ports:"; then
        echo "   ⚠️  WARNING: API service has 'ports:' section (should not have this with Traefik)"
    fi
    
elif grep -A 50 "^  api:" "$STACK_FILE" | grep -q "^    ports:"; then
    echo "   🚪 Direct port mapping detected"
    
    # Check for ports configuration
    if grep -A 50 "^  api:" "$STACK_FILE" | grep -q "published:"; then
        echo "   ✅ Has 'published:' port configuration"
    else
        echo "   ❌ ERROR: Missing port configuration"
        ERRORS=$((ERRORS + 1))
    fi
    
    # Check that traefik labels are NOT defined
    if grep -q "traefik.enable" "$STACK_FILE"; then
        echo "   ⚠️  WARNING: Has Traefik labels (should not have these with direct ports)"
    fi
else
    echo "   ⚠️  WARNING: No proxy configuration detected (neither Traefik nor direct ports)"
fi

echo ""
echo "================================"

if [ $ERRORS -eq 0 ]; then
    echo "✅ Validation passed! Stack file looks good."
    exit 0
else
    echo "❌ Validation failed with $ERRORS error(s)"
    exit 1
fi
