# Validation script for swarm-stack.yml
# Tests that the generated stack file is correct and has no placeholders

param(
    [string]$StackFile = "swarm-stack.yml"
)

$ErrorActionPreference = "Continue"
$Errors = 0

Write-Host "🔍 Validating $StackFile..." -ForegroundColor Cyan
Write-Host "================================"
Write-Host ""

# Check if file exists
if (-not (Test-Path $StackFile)) {
    Write-Host "❌ ERROR: File $StackFile not found" -ForegroundColor Red
    exit 1
}

$content = Get-Content $StackFile -Raw

# Check for unreplaced placeholders
Write-Host "1️⃣  Checking for unreplaced placeholders..."
$placeholders = Select-String -Pattern "###" -Path $StackFile
if ($placeholders) {
    Write-Host "   ❌ ERROR: Found unreplaced placeholders:" -ForegroundColor Red
    $placeholders | ForEach-Object {
        Write-Host "      Line $($_.LineNumber): $($_.Line.Trim())"
    }
    $Errors++
} else {
    Write-Host "   ✅ No placeholders found" -ForegroundColor Green
}
Write-Host ""

# Check for XXX_ placeholders that should have been replaced
Write-Host "2️⃣  Checking for unreplaced XXX_ placeholders..."
$xxxPlaceholders = Select-String -Pattern "XXX_CHANGE_ME_" -Path $StackFile
if ($xxxPlaceholders) {
    Write-Host "   ⚠️  WARNING: Found unreplaced XXX_ placeholders (this is OK before running wizard):" -ForegroundColor Yellow
    $xxxPlaceholders | Select-Object -First 5 | ForEach-Object {
        Write-Host "      Line $($_.LineNumber): $($_.Line.Trim())"
    }
} else {
    Write-Host "   ✅ All XXX_ placeholders replaced" -ForegroundColor Green
}
Write-Host ""

# Validate YAML syntax with docker (if available)
Write-Host "3️⃣  Validating YAML syntax..."
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $null = docker stack config -c $StackFile 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   ✅ Valid Docker Compose YAML syntax" -ForegroundColor Green
    } else {
        Write-Host "   ❌ ERROR: Invalid YAML syntax" -ForegroundColor Red
        Write-Host "      Run: docker stack config -c $StackFile"
        $Errors++
    }
} else {
    Write-Host "   ⚠️  WARNING: Docker not found, skipping syntax validation" -ForegroundColor Yellow
}
Write-Host ""

# Check for common issues
Write-Host "4️⃣  Checking structure..."

# Check for services key
if ($content -match "^services:") {
    Write-Host "   ✅ Has 'services:' key" -ForegroundColor Green
} else {
    Write-Host "   ❌ ERROR: Missing 'services:' key" -ForegroundColor Red
    $Errors++
}

# Check for networks key
if ($content -match "^networks:") {
    Write-Host "   ✅ Has 'networks:' key" -ForegroundColor Green
} else {
    Write-Host "   ❌ ERROR: Missing 'networks:' key" -ForegroundColor Red
    $Errors++
}

# Check for secrets key
if ($content -match "^secrets:") {
    Write-Host "   ✅ Has 'secrets:' key" -ForegroundColor Green
} else {
    Write-Host "   ❌ ERROR: Missing 'secrets:' key" -ForegroundColor Red
    $Errors++
}

# Check for api service
if ($content -match "^  api:") {
    Write-Host "   ✅ Has 'api' service" -ForegroundColor Green
} else {
    Write-Host "   ❌ ERROR: Missing 'api' service" -ForegroundColor Red
    $Errors++
}

# Check for redis service
if ($content -match "^  redis:") {
    Write-Host "   ✅ Has 'redis' service" -ForegroundColor Green
} else {
    Write-Host "   ❌ ERROR: Missing 'redis' service" -ForegroundColor Red
    $Errors++
}

Write-Host ""

# Check proxy configuration
Write-Host "5️⃣  Checking proxy configuration..."
if ($content -match "traefik.enable=true") {
    Write-Host "   📡 Traefik proxy detected" -ForegroundColor Cyan
    
    # Check for required traefik labels
    $requiredLabels = @(
        "traefik.enable=true",
        "traefik.constraint-label=traefik-public",
        "traefik.docker.network",
        "traefik.http.routers",
        "traefik.http.services"
    )
    
    foreach ($label in $requiredLabels) {
        if ($content -match [regex]::Escape($label)) {
            Write-Host "   ✅ Has label: $label" -ForegroundColor Green
        } else {
            Write-Host "   ❌ ERROR: Missing label: $label" -ForegroundColor Red
            $Errors++
        }
    }
    
    # Check that ports are NOT defined for api service
    if ($content -match "(?ms)^  api:.*?^    ports:") {
        Write-Host "   ⚠️  WARNING: API service has 'ports:' section (should not have this with Traefik)" -ForegroundColor Yellow
    }
    
} elseif ($content -match "(?ms)^  api:.*?^    ports:") {
    Write-Host "   🚪 Direct port mapping detected" -ForegroundColor Cyan
    
    # Check for ports configuration
    if ($content -match "published:") {
        Write-Host "   ✅ Has 'published:' port configuration" -ForegroundColor Green
    } else {
        Write-Host "   ❌ ERROR: Missing port configuration" -ForegroundColor Red
        $Errors++
    }
    
    # Check that traefik labels are NOT defined
    if ($content -match "traefik.enable") {
        Write-Host "   ⚠️  WARNING: Has Traefik labels (should not have these with direct ports)" -ForegroundColor Yellow
    }
} else {
    Write-Host "   ⚠️  WARNING: No proxy configuration detected (neither Traefik nor direct ports)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "================================"

if ($Errors -eq 0) {
    Write-Host "✅ Validation passed! Stack file looks good." -ForegroundColor Green
    exit 0
} else {
    Write-Host "❌ Validation failed with $Errors error(s)" -ForegroundColor Red
    exit 1
}
