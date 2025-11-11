# Data directory creation module
# Creates required data directories with existence checks

function New-DataDirectories {
    param(
        [string]$DataRoot,
        [string]$DbType
    )
    
    Write-Host "📁 Creating Data Directories" -ForegroundColor Cyan
    Write-Host "============================"
    Write-Host ""
    
    # Create main data root
    if (Test-Path $DataRoot) {
        Write-Host "✅ Data root already exists: $DataRoot" -ForegroundColor Green
    } else {
        Write-Host "Creating data root: $DataRoot"
        try {
            New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
            Write-Host "✅ Created: $DataRoot" -ForegroundColor Green
        } catch {
            Write-Host "❌ Failed to create: $DataRoot" -ForegroundColor Red
            return $false
        }
    }
    
    # Create database-specific directories
    if ($DbType -eq "postgresql") {
        $PostgresPath = Join-Path $DataRoot "postgres_data"
        if (Test-Path $PostgresPath) {
            Write-Host "✅ PostgreSQL data directory already exists" -ForegroundColor Green
        } else {
            Write-Host "Creating PostgreSQL data directory..."
            try {
                New-Item -ItemType Directory -Path $PostgresPath -Force | Out-Null
                Write-Host "✅ Created: $PostgresPath" -ForegroundColor Green
            } catch {
                Write-Host "❌ Failed to create: $PostgresPath" -ForegroundColor Red
                return $false
            }
        }
    } elseif ($DbType -eq "neo4j") {
        $Neo4jDataPath = Join-Path $DataRoot "neo4j_data"
        if (Test-Path $Neo4jDataPath) {
            Write-Host "✅ Neo4j data directory already exists" -ForegroundColor Green
        } else {
            Write-Host "Creating Neo4j data directory..."
            try {
                New-Item -ItemType Directory -Path $Neo4jDataPath -Force | Out-Null
                Write-Host "✅ Created: $Neo4jDataPath" -ForegroundColor Green
            } catch {
                Write-Host "❌ Failed to create: $Neo4jDataPath" -ForegroundColor Red
                return $false
            }
        }
        
        $Neo4jLogsPath = Join-Path $DataRoot "neo4j_logs"
        if (Test-Path $Neo4jLogsPath) {
            Write-Host "✅ Neo4j logs directory already exists" -ForegroundColor Green
        } else {
            Write-Host "Creating Neo4j logs directory..."
            try {
                New-Item -ItemType Directory -Path $Neo4jLogsPath -Force | Out-Null
                Write-Host "✅ Created: $Neo4jLogsPath" -ForegroundColor Green
            } catch {
                Write-Host "❌ Failed to create: $Neo4jLogsPath" -ForegroundColor Red
                return $false
            }
        }
    }
    
    # Create Backup directory
    $BackupPath = Join-Path $DataRoot "backups"
    if (Test-Path $BackupPath) {
        Write-Host "✅ Backup data directory already exists" -ForegroundColor Green
    } else {
        Write-Host "Creating Backup data directory..."
        try {
            New-Item -ItemType Directory -Path $BackupPath -Force | Out-Null
            Write-Host "✅ Created: $BackupPath" -ForegroundColor Green
        } catch {
            Write-Host "❌ Failed to create: $BackupPath" -ForegroundColor Red
            return $false
        }
    }
    
    # Create Redis directory
    $RedisPath = Join-Path $DataRoot "redis_data"
    if (Test-Path $RedisPath) {
        Write-Host "✅ Redis data directory already exists" -ForegroundColor Green
    } else {
        Write-Host "Creating Redis data directory..."
        try {
            New-Item -ItemType Directory -Path $RedisPath -Force | Out-Null
            Write-Host "✅ Created: $RedisPath" -ForegroundColor Green
        } catch {
            Write-Host "❌ Failed to create: $RedisPath" -ForegroundColor Red
            return $false
        }
    }
    
    Write-Host ""
    Write-Host "✅ All data directories ready" -ForegroundColor Green
    Write-Host ""
    
    return $true
}

Export-ModuleMember -Function New-DataDirectories
