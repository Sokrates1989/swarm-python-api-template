# User prompts module
# Handles all user input collection

function Get-DatabaseType {
    Write-Host "🗄️  Database Configuration" -ForegroundColor Cyan
    Write-Host "-------------------------"
    Write-Host "1) PostgreSQL (relational data)"
    Write-Host "2) Neo4j (graph data)"
    Write-Host ""
    $DbChoice = Read-Host "Your choice (1-2) [1]"
    if ([string]::IsNullOrWhiteSpace($DbChoice)) { $DbChoice = "1" }
    
    switch ($DbChoice) {
        "1" { return "postgresql" }
        "2" { return "neo4j" }
        default { return "postgresql" }
    }
}

function Get-ProxyType {
    Write-Host "🌐 Proxy Configuration" -ForegroundColor Cyan
    Write-Host "---------------------"
    Write-Host "1) Traefik (automatic HTTPS)"
    Write-Host "2) No proxy (direct port)"
    Write-Host ""
    $ProxyChoice = Read-Host "Your choice (1-2) [1]"
    if ([string]::IsNullOrWhiteSpace($ProxyChoice)) { $ProxyChoice = "1" }
    
    switch ($ProxyChoice) {
        "1" { return "traefik" }
        "2" { return "none" }
        default { return "traefik" }
    }
}

function Get-DatabaseMode {
    Write-Host "📍 Database Mode" -ForegroundColor Cyan
    Write-Host "---------------"
    Write-Host "1) Local (deploy in swarm)"
    Write-Host "2) External (existing server)"
    Write-Host ""
    $DbModeChoice = Read-Host "Your choice (1-2) [1]"
    if ([string]::IsNullOrWhiteSpace($DbModeChoice)) { $DbModeChoice = "1" }
    
    switch ($DbModeChoice) {
        "1" { return "local" }
        "2" { return "external" }
        default { return "local" }
    }
}

function Get-StackName {
    $StackName = Read-Host "Stack name [python-api-template]"
    if ([string]::IsNullOrWhiteSpace($StackName)) {
        return "python-api-template"
    }
    return $StackName
}

function Get-DataRoot {
    param([string]$DefaultPath)
    
    $DataRoot = Read-Host "Data root directory [$DefaultPath]"
    if ([string]::IsNullOrWhiteSpace($DataRoot)) {
        return $DefaultPath
    }
    return $DataRoot
}

function Get-ApiDomain {
    $ApiUrl = ""
    while ([string]::IsNullOrWhiteSpace($ApiUrl)) {
        $ApiUrl = Read-Host "API domain (e.g., api.example.com)"
        if ([string]::IsNullOrWhiteSpace($ApiUrl)) {
            Write-Host "⚠️  Domain is required for Traefik" -ForegroundColor Yellow
        }
    }
    return $ApiUrl
}

function Get-PublishedPort {
    $PublishedPort = Read-Host "Published port [8000]"
    if ([string]::IsNullOrWhiteSpace($PublishedPort)) {
        return "8000"
    }
    return $PublishedPort
}

function Get-DockerImage {
    Write-Host ""
    Write-Host "🐳 Docker Image Configuration" -ForegroundColor Cyan
    Write-Host "----------------------------"
    
    $imageVerified = $false
    $imageName = ""
    $imageVersion = ""
    
    while (-not $imageVerified) {
        $imageName = Read-Host "Docker image name (e.g., sokrates1989/python-api-template)"
        $imageVersion = Read-Host "Image version [latest]"
        if ([string]::IsNullOrWhiteSpace($imageVersion)) {
            $imageVersion = "latest"
        }
        
        Write-Host "Verifying image: ${imageName}:${imageVersion}"
        docker pull "${imageName}:${imageVersion}" 2>&1 | Out-Null
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✅ Image verified" -ForegroundColor Green
            $imageVerified = $true
        } else {
            Write-Host ""
            Write-Host "❌ Failed to pull image" -ForegroundColor Red
            Write-Host "1) Login to Docker registry"
            Write-Host "2) Re-enter image info"
            Write-Host "3) Skip verification"
            Write-Host "4) Cancel setup"
            $ImageChoice = Read-Host "Your choice (1-4)"
            
            switch ($ImageChoice) {
                "1" { docker login }
                "2" { continue }
                "3" { $imageVerified = $true }
                "4" { return $null }
            }
        }
    }
    
    return @{
        Name = $imageName
        Version = $imageVersion
    }
}

function Get-Replicas {
    param(
        [string]$ServiceName,
        [int]$DefaultCount = 1
    )
    
    $Replicas = Read-Host "$ServiceName replicas [$DefaultCount]"
    if ([string]::IsNullOrWhiteSpace($Replicas)) {
        return $DefaultCount
    }
    return [int]$Replicas
}

function Get-SecretNames {
    param([string]$StackName)
    
    $StackNameUpper = $StackName.ToUpper() -replace '[^A-Z0-9]', '_'
    
    $DbPasswordSecret = Read-Host "Database password secret [${StackNameUpper}_DB_PASSWORD]"
    if ([string]::IsNullOrWhiteSpace($DbPasswordSecret)) {
        $DbPasswordSecret = "${StackNameUpper}_DB_PASSWORD"
    }
    
    $AdminApiKeySecret = Read-Host "Admin API key secret [${StackNameUpper}_ADMIN_API_KEY]"
    if ([string]::IsNullOrWhiteSpace($AdminApiKeySecret)) {
        $AdminApiKeySecret = "${StackNameUpper}_ADMIN_API_KEY"
    }
    
    return @{
        DbPassword = $DbPasswordSecret
        AdminApiKey = $AdminApiKeySecret
    }
}

function Get-YesNo {
    param(
        [string]$PromptText,
        [string]$Default = "Y"
    )
    
    if ($Default -eq "Y") {
        $Response = Read-Host "$PromptText (Y/n)"
        return ($Response -ne "n" -and $Response -ne "N")
    } else {
        $Response = Read-Host "$PromptText (y/N)"
        return ($Response -eq "y" -or $Response -eq "Y")
    }
}

Export-ModuleMember -Function Get-DatabaseType, Get-ProxyType, Get-DatabaseMode, Get-StackName, Get-DataRoot, Get-ApiDomain, Get-PublishedPort, Get-DockerImage, Get-Replicas, Get-SecretNames, Get-YesNo
