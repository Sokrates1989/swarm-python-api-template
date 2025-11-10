#!/bin/bash
# Test script to verify swarm-stack.yml generation logic
# This simulates what the config-builder does

set -e

PROJECT_ROOT="$(pwd)"
echo "🧪 Testing swarm-stack.yml generation..."
echo "========================================"
echo ""

# Test 1: PostgreSQL Local + Traefik
echo "Test 1: PostgreSQL Local + Traefik"
echo "-----------------------------------"

OUTPUT_FILE="test-output-traefik.yml"
TEMP_API="test-api-temp.yml"

# Start with base
cat "${PROJECT_ROOT}/setup/compose-modules/base.yml" > "$OUTPUT_FILE"

# Build API service from template
cp "${PROJECT_ROOT}/setup/compose-modules/api.template.yml" "$TEMP_API"

# Inject database environment snippet
DB_ENV_SNIPPET="${PROJECT_ROOT}/setup/compose-modules/snippets/db-postgres-local.env.yml"
if [ -f "$DB_ENV_SNIPPET" ]; then
    sed -i "/###DATABASE_ENV###/r $DB_ENV_SNIPPET" "$TEMP_API"
    sed -i '/###DATABASE_ENV###/d' "$TEMP_API"
fi

# Inject proxy network snippet
PROXY_NETWORK_SNIPPET="${PROJECT_ROOT}/setup/compose-modules/snippets/proxy-traefik.network.yml"
if [ -f "$PROXY_NETWORK_SNIPPET" ]; then
    sed -i "/###PROXY_NETWORK###/r $PROXY_NETWORK_SNIPPET" "$TEMP_API"
fi
sed -i '/###PROXY_NETWORK###/d' "$TEMP_API"

# Inject Traefik labels
PROXY_LABELS_SNIPPET="${PROJECT_ROOT}/setup/compose-modules/snippets/proxy-traefik.labels.yml"
if [ -f "$PROXY_LABELS_SNIPPET" ]; then
    sed -i "/###PROXY_LABELS###/r $PROXY_LABELS_SNIPPET" "$TEMP_API"
fi
sed -i '/###PROXY_LABELS###/d' "$TEMP_API"
sed -i '/###PROXY_PORTS###/d' "$TEMP_API"

# Append API service
cat "$TEMP_API" >> "$OUTPUT_FILE"
rm -f "$TEMP_API"

# Add PostgreSQL service
cat "${PROJECT_ROOT}/setup/compose-modules/postgres-local.yml" >> "$OUTPUT_FILE"

# Add footer
cat "${PROJECT_ROOT}/setup/compose-modules/footer.yml" >> "$OUTPUT_FILE"

# Check results
echo "Checking for placeholders..."
if grep -q "###" "$OUTPUT_FILE"; then
    echo "❌ FAILED: Found unreplaced placeholders:"
    grep -n "###" "$OUTPUT_FILE"
    exit 1
else
    echo "✅ PASSED: No placeholders found"
fi

echo "Checking for Traefik labels..."
if grep -q "traefik.enable=true" "$OUTPUT_FILE"; then
    echo "✅ PASSED: Traefik labels found"
else
    echo "❌ FAILED: Traefik labels not found"
    exit 1
fi

echo "Checking that ports are NOT present..."
if grep -A 50 "^  api:" "$OUTPUT_FILE" | grep -q "^    ports:"; then
    echo "❌ FAILED: Found ports section (should not be present with Traefik)"
    exit 1
else
    echo "✅ PASSED: No ports section found"
fi

echo ""
echo "Test 1: ✅ PASSED"
echo ""

# Test 2: PostgreSQL Local + Direct Port
echo "Test 2: PostgreSQL Local + Direct Port"
echo "---------------------------------------"

OUTPUT_FILE="test-output-direct.yml"
TEMP_API="test-api-temp.yml"

# Start with base
cat "${PROJECT_ROOT}/setup/compose-modules/base.yml" > "$OUTPUT_FILE"

# Build API service from template
cp "${PROJECT_ROOT}/setup/compose-modules/api.template.yml" "$TEMP_API"

# Inject database environment snippet
DB_ENV_SNIPPET="${PROJECT_ROOT}/setup/compose-modules/snippets/db-postgres-local.env.yml"
if [ -f "$DB_ENV_SNIPPET" ]; then
    sed -i "/###DATABASE_ENV###/r $DB_ENV_SNIPPET" "$TEMP_API"
    sed -i '/###DATABASE_ENV###/d' "$TEMP_API"
fi

# No proxy network for direct mode
sed -i '/###PROXY_NETWORK###/d' "$TEMP_API"

# Inject ports
PROXY_PORTS_SNIPPET="${PROJECT_ROOT}/setup/compose-modules/snippets/proxy-none.ports.yml"
if [ -f "$PROXY_PORTS_SNIPPET" ]; then
    sed -i "/###PROXY_PORTS###/r $PROXY_PORTS_SNIPPET" "$TEMP_API"
fi
sed -i '/###PROXY_PORTS###/d' "$TEMP_API"
sed -i '/###PROXY_LABELS###/d' "$TEMP_API"

# Append API service
cat "$TEMP_API" >> "$OUTPUT_FILE"
rm -f "$TEMP_API"

# Add PostgreSQL service
cat "${PROJECT_ROOT}/setup/compose-modules/postgres-local.yml" >> "$OUTPUT_FILE"

# Add footer
cat "${PROJECT_ROOT}/setup/compose-modules/footer.yml" >> "$OUTPUT_FILE"

# Check results
echo "Checking for placeholders..."
if grep -q "###" "$OUTPUT_FILE"; then
    echo "❌ FAILED: Found unreplaced placeholders:"
    grep -n "###" "$OUTPUT_FILE"
    exit 1
else
    echo "✅ PASSED: No placeholders found"
fi

echo "Checking for ports section..."
if grep -A 50 "^  api:" "$OUTPUT_FILE" | grep -q "^    ports:"; then
    echo "✅ PASSED: Ports section found"
else
    echo "❌ FAILED: Ports section not found"
    exit 1
fi

echo "Checking that Traefik labels are NOT present..."
if grep -q "traefik.enable" "$OUTPUT_FILE"; then
    echo "❌ FAILED: Found Traefik labels (should not be present with direct ports)"
    exit 1
else
    echo "✅ PASSED: No Traefik labels found"
fi

echo ""
echo "Test 2: ✅ PASSED"
echo ""

# Summary
echo "========================================"
echo "✅ All tests passed!"
echo ""
echo "Generated test files:"
echo "  - test-output-traefik.yml"
echo "  - test-output-direct.yml"
echo ""
echo "You can inspect these files to verify the output."
