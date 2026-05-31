#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Build Docker Swarm stack for a specific site

.DESCRIPTION
    Reads site configuration from site-configs/{SiteId}.json
    and generates deployments/{SiteId}/swarm-stack.yml

.PARAMETER SiteId
    The site ID to build (e.g., "api-demo")

.EXAMPLE
    .\build-site-stack.ps1 -SiteId "api-demo"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$SiteId
)

$ErrorActionPreference = "Stop"

# Paths
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$configPath = Join-Path $projectRoot "site-configs" "${SiteId}.json"
$deploymentDir = Join-Path $projectRoot "deployments" $SiteId
$envFile = Join-Path $deploymentDir ".env"
$outputFile = Join-Path $deploymentDir "swarm-stack.yml"

# Verify site config exists
if (-not (Test-Path $configPath)) {
    Write-Error "Site configuration not found: $configPath"
    exit 1
}

# Load site config
$config = Get-Content $configPath | ConvertFrom-Json

Write-Host "Building stack for site: ${SiteId}" -ForegroundColor Cyan
Write-Host "  Name: $($config.name)"
Write-Host "  Domain: $($config.domain)"
Write-Host "  Database: $($config.database.type) ($($config.database.mode))"

# Build compose file list
$composeFiles = @()

# 1. Base (networks, secrets)
$baseFile = Join-Path $projectRoot "deployments" "_base" "base.yml"
if (Test-Path $baseFile) {
    $composeFiles += $baseFile
}

# 2. Site-specific files (in order)
$siteFiles = @(
    Join-Path $deploymentDir "api.yml"
)

# 3. Database module (type-specific)
switch ($config.database.type) {
    "postgresql" {
        if ($config.database.mode -eq "local") {
            $postgresFile = Join-Path $deploymentDir "postgres.yml"
            if (Test-Path $postgresFile) {
                $siteFiles += $postgresFile
            }
        }
    }
    default {
        Write-Warning "Unsupported database type: $($config.database.type)"
    }
}

# Add all site files
foreach ($file in $siteFiles) {
    if (Test-Path $file) {
        $composeFiles += $file
    } else {
        Write-Warning "Missing compose file: $file"
    }
}

Write-Host ""
Write-Host "Compose files to merge:"
foreach ($file in $composeFiles) {
    Write-Host "  - $(Split-Path $file -Leaf)"
}

# Generate stack using docker compose config
# Note: This requires Docker to be running
Write-Host ""
Write-Host "Generating swarm-stack.yml..."

try {
    $composeArgs = @()
    foreach ($file in $composeFiles) {
        $composeArgs += "-f"
        $composeArgs += $file
    }
    $composeArgs += "--env-file"
    $composeArgs += $envFile
    $composeArgs += "config"

    # Run docker compose config
    $output = & docker compose @composeArgs 2>&1

    if ($LASTEXITCODE -ne 0) {
        Write-Error "Docker compose config failed: $output"
        exit 1
    }

    # Write output file
    $output | Set-Content $outputFile -Encoding UTF8

    Write-Host "Stack generated: $outputFile" -ForegroundColor Green

} catch {
    Write-Error "Failed to generate stack: $_"
    exit 1
}

Write-Host ""
Write-Host "To deploy this site, run:" -ForegroundColor Yellow
Write-Host "  docker stack deploy -c ${outputFile} ${SiteId}"
