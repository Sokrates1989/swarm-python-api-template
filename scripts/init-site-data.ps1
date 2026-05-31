#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Initialize data directories for a site

.DESCRIPTION
    Creates the necessary directory structure for site data persistence.

.PARAMETER SiteId
    The site ID to initialize

.EXAMPLE
    .\init-site-data.ps1 -SiteId "api-demo"
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
$dataDir = Join-Path $deploymentDir "data"

# Verify site exists
if (-not (Test-Path $configPath)) {
    Write-Error "Site '${SiteId}' not found in site-configs/"
    exit 1
}

# Load database type from config
$config = Get-Content $configPath | ConvertFrom-Json
$dbType = $config.database.type

Write-Host "Initializing data directories for site: ${SiteId}" -ForegroundColor Cyan
Write-Host "  Database type: ${dbType}"
Write-Host ""

# Create base directories
New-Item -ItemType Directory -Force -Path (Join-Path $dataDir "logs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $dataDir "redis") | Out-Null

# Create database-specific directories
switch ($dbType) {
    "postgresql" {
        New-Item -ItemType Directory -Force -Path (Join-Path $dataDir "postgres") | Out-Null
        Write-Host "  Created: $(Join-Path $dataDir "postgres")"
    }
    "mongodb" {
        New-Item -ItemType Directory -Force -Path (Join-Path $dataDir "mongodb") | Out-Null
        Write-Host "  Created: $(Join-Path $dataDir "mongodb")"
    }
    default {
        Write-Warning "Unknown database type: ${dbType}"
    }
}

Write-Host "  Created: $(Join-Path $dataDir "redis")"
Write-Host "  Created: $(Join-Path $dataDir "logs")"

Write-Host ""
Write-Host "Data directories initialized for ${SiteId}" -ForegroundColor Green
