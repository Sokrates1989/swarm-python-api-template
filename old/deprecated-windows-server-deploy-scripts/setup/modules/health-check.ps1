# Health check module for deployed stacks

function Test-DeploymentHealth {
    param(
        [string]$StackName,
        [string]$DbType,
        [string]$ProxyType,
        [string]$ApiUrl,
        [int]$WaitSeconds = 0  # Default to 0 if not provided
    )
    
    Write-Host "🏥 Health Check" -ForegroundColor Cyan
    Write-Host "==============="
    Write-Host ""
    
    # Define services to check
    $services = @("api", "redis")
    
    if ($DbType -eq "postgresql") {
        $services += "postgres"
    } elseif ($DbType -eq "neo4j") {
        $services += "neo4j"
    }
    
    # Wait for services to become healthy (max 3 minutes)
    $maxWait = 180  # 3 minutes
    $checkInterval = 5
    $elapsed = 0
    $allHealthy = $false
    
    Write-Host "Waiting for all services to become healthy (max 3 minutes)..."
    Write-Host ""
    
    while ($elapsed -lt $maxWait -and -not $allHealthy) {
        $allHealthy = $true
        
        foreach ($service in $services) {
            $serviceName = "${StackName}_${service}"
            $replicas = docker service ls --filter "name=${serviceName}" --format "{{.Replicas}}" 2>$null
            
            if ($replicas -match "^(\d+)/(\d+)") {
                $current = $matches[1]
                $desired = $matches[2]
                
                if ($current -ne $desired) {
                    $allHealthy = $false
                    Write-Host "[${elapsed}s] ⏳ Service $service : $replicas (waiting...)" -ForegroundColor Yellow
                }
            }
        }
        
        if (-not $allHealthy) {
            Start-Sleep -Seconds $checkInterval
            $elapsed += $checkInterval
        }
    }
    
    # Final status check
    Write-Host ""
    Write-Host "Final service status:"
    Write-Host ""
    docker stack services $StackName
    Write-Host ""
    
    # Check each service
    foreach ($service in $services) {
        $serviceName = "${StackName}_${service}"
        $replicas = docker service ls --filter "name=${serviceName}" --format "{{.Replicas}}"
        
        if ($replicas -match "^(\d+)/(\d+)") {
            $current = $matches[1]
            $desired = $matches[2]
            
            if ($current -ne $desired) {
                Write-Host "❌ Service $service has unequal replicas: $replicas" -ForegroundColor Red
            } else {
                Write-Host "✅ Service $service is healthy: $replicas" -ForegroundColor Green
            }
        }
    }
    
    # Show detailed task status for all services
    Write-Host ""
    Write-Host "Service task details:"
    Write-Host ""
    foreach ($service in $services) {
        $serviceName = "${StackName}_${service}"
        Write-Host "ℹ️  ${serviceName}:" -ForegroundColor Cyan
        docker service ps $serviceName --no-trunc
        Write-Host ""
    }
    
    if (-not $allHealthy) {
        Write-Host ""
        Write-Host "⚠️  Some services did not become healthy within 3 minutes." -ForegroundColor Yellow
        Write-Host ""
    }
    
    # Check logs
    Write-Host ""
    Write-Host "Checking service logs..."
    Write-Host ""

    # Wait for services to initialize (if configured)
    if ($WaitSeconds -gt 0) {
        Write-Host "⏳ Waiting $WaitSeconds seconds for services to initialize..." -ForegroundColor Yellow
        Start-Sleep -Seconds $WaitSeconds
        Write-Host ""
    }
    
    # Check API logs (increased to 50 lines to capture connection success)
    Write-Host "--- API Logs ---" -ForegroundColor Cyan
    docker service logs "${StackName}_api" --tail 50 2>&1 | Select-String -Pattern "startup|ready|error|failed|connection|database|migration" -CaseSensitive:$false
    if (-not $?) {
        Write-Host "No relevant log entries found"
    }
    Write-Host ""
    
    # Check database logs
    if ($DbType -eq "postgresql") {
        Write-Host "--- PostgreSQL Logs ---" -ForegroundColor Cyan
        docker service logs "${StackName}_postgres" --tail 30 2>&1 | Select-String -Pattern "ready|accept|error|failed|connection" -CaseSensitive:$false
        if (-not $?) {
            Write-Host "No relevant log entries found"
        }
        Write-Host ""
    } elseif ($DbType -eq "neo4j") {
        Write-Host "--- Neo4j Logs ---" -ForegroundColor Cyan
        docker service logs "${StackName}_neo4j" --tail 20 2>&1 | Select-String -Pattern "started|remote|error|failed" -CaseSensitive:$false
        if (-not $?) {
            Write-Host "No relevant log entries found"
        }
        Write-Host ""
    }
    
    # Check Redis logs
    Write-Host "--- Redis Logs ---" -ForegroundColor Cyan
    docker service logs "${StackName}_redis" --tail 20 2>&1 | Select-String -Pattern "ready|accept|error|failed" -CaseSensitive:$false
    if (-not $?) {
        Write-Host "No relevant log entries found"
    }
    Write-Host ""
    
    # Test API health endpoint
    if ($ProxyType -eq "traefik") {
        Write-Host "Testing API health endpoint..."
        Write-Host "URL: https://${ApiUrl}/health"
        Write-Host ""
        
        try {
            $HealthResponse = Invoke-WebRequest -Uri "https://${ApiUrl}/health" -UseBasicParsing -SkipCertificateCheck -TimeoutSec 5 -ErrorAction Stop
            if ($HealthResponse.Content -match "healthy") {
                Write-Host "✅ API health check passed" -ForegroundColor Green
                Write-Host "Response: $($HealthResponse.Content)"
            } else {
                Write-Host "⚠️  API health check returned unexpected response" -ForegroundColor Yellow
                Write-Host "Response: $($HealthResponse.Content)"
            }
        } catch {
            Write-Host "⚠️  API health check failed or not yet ready" -ForegroundColor Yellow
            Write-Host "Error: $($_.Exception.Message)"
            Write-Host ""
            Write-Host "This might be normal if the API is still initializing."
            Write-Host "Wait a few more minutes and try: curl https://${ApiUrl}/health"
        }
    }
    
    Write-Host ""
    Write-Host "📋 Health Check Summary" -ForegroundColor Cyan
    Write-Host "======================="
    Write-Host ""
    Write-Host "Stack checked: $StackName"
    Write-Host ""
    Write-Host "Useful commands:"
    Write-Host "  docker stack services $StackName          # Check service status"
    Write-Host "  docker service logs ${StackName}_api      # View API logs"
    Write-Host "  docker service ps ${StackName}_api        # Check API tasks"
    Write-Host ""
    
    return $true
}

# Create alias for easier calling
Set-Alias -Name Check-DeploymentHealth -Value Test-DeploymentHealth

Export-ModuleMember -Function Test-DeploymentHealth -Alias Check-DeploymentHealth
