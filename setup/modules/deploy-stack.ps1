# Stack deployment and health check module

function Invoke-StackDeploy {
    param(
        [string]$StackName,
        [string]$StackFile
    )
    
    Write-Host "🚀 Deploying Stack" -ForegroundColor Cyan
    Write-Host "=================="
    Write-Host ""
    Write-Host "Stack name: $StackName"
    Write-Host "Stack file: $StackFile"
    Write-Host ""
    
    $ConfirmDeploy = Read-Host "Deploy now? (Y/n)"
    if ($ConfirmDeploy -eq "n" -or $ConfirmDeploy -eq "N") {
        Write-Host "Deployment cancelled."
        return $false
    }
    
    Write-Host ""
    Write-Host "Deploying stack..."
    docker stack deploy -c $StackFile $StackName
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Deployment failed" -ForegroundColor Red
        return $false
    }
    
    Write-Host ""
    Write-Host "✅ Stack deployed successfully" -ForegroundColor Green
    Write-Host ""
    
    return $true
}

function Test-DeploymentHealth {
    param(
        [string]$StackName,
        [string]$DbType,
        [string]$ProxyType,
        [string]$ApiUrl
    )
    
    Write-Host "🏥 Health Check" -ForegroundColor Cyan
    Write-Host "==============="
    Write-Host ""
    Write-Host "Waiting for services to start (10 seconds)..."
    Start-Sleep -Seconds 10
    
    # Check service replicas
    Write-Host ""
    Write-Host "Checking service replicas..."
    Write-Host ""
    docker stack services $StackName
    Write-Host ""
    
    # Get service status
    $allHealthy = $true
    $services = @("api", "redis")
    
    if ($DbType -eq "postgresql") {
        $services += "postgres"
    } elseif ($DbType -eq "neo4j") {
        $services += "neo4j"
    }
    
    foreach ($service in $services) {
        $serviceName = "${StackName}_${service}"
        $replicas = docker service ls --filter "name=${serviceName}" --format "{{.Replicas}}"
        
        if ($replicas -match "^(\d+)/(\d+)") {
            $current = $matches[1]
            $desired = $matches[2]
            
            if ($current -ne $desired) {
                Write-Host "⚠️  Service $service has unequal replicas: $replicas" -ForegroundColor Yellow
                $allHealthy = $false
                
                Write-Host "   Checking service tasks..."
                docker service ps $serviceName --no-trunc
                Write-Host ""
            } else {
                Write-Host "✅ Service $service is healthy: $replicas" -ForegroundColor Green
            }
        }
    }
    
    if (-not $allHealthy) {
        Write-Host ""
        Write-Host "❌ Some services have issues. Check the output above for details." -ForegroundColor Red
        Write-Host ""
        $ContinueLogs = Read-Host "Continue with log checks anyway? (y/N)"
        if ($ContinueLogs -ne "y" -and $ContinueLogs -ne "Y") {
            return $false
        }
    }
    
    # Wait for services to fully initialize
    Write-Host ""
    Write-Host "Waiting for services to initialize (30 seconds)..."
    Start-Sleep -Seconds 30
    
    # Check logs
    Write-Host ""
    Write-Host "Checking service logs..."
    Write-Host ""
    
    # Check API logs
    Write-Host "--- API Logs ---" -ForegroundColor Cyan
    docker service logs "${StackName}_api" --tail 20 2>&1 | Select-String -Pattern "startup|ready|error|failed" -CaseSensitive:$false
    Write-Host ""
    
    # Check database logs
    if ($DbType -eq "postgresql") {
        Write-Host "--- PostgreSQL Logs ---" -ForegroundColor Cyan
        docker service logs "${StackName}_postgres" --tail 20 2>&1 | Select-String -Pattern "ready|accept|error|failed" -CaseSensitive:$false
        Write-Host ""
    } elseif ($DbType -eq "neo4j") {
        Write-Host "--- Neo4j Logs ---" -ForegroundColor Cyan
        docker service logs "${StackName}_neo4j" --tail 20 2>&1 | Select-String -Pattern "started|remote|error|failed" -CaseSensitive:$false
        Write-Host ""
    }
    
    # Check Redis logs
    Write-Host "--- Redis Logs ---" -ForegroundColor Cyan
    docker service logs "${StackName}_redis" --tail 20 2>&1 | Select-String -Pattern "ready|accept|error|failed" -CaseSensitive:$false
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
    Write-Host "📋 Deployment Summary" -ForegroundColor Cyan
    Write-Host "===================="
    Write-Host ""
    Write-Host "Stack deployed: $StackName"
    Write-Host ""
    Write-Host "Useful commands:"
    Write-Host "  docker stack services $StackName          # Check service status"
    Write-Host "  docker service logs ${StackName}_api      # View API logs"
    Write-Host "  docker service ps ${StackName}_api        # Check API tasks"
    Write-Host "  docker stack rm $StackName                # Remove stack"
    Write-Host ""
    
    return $true
}

Export-ModuleMember -Function Invoke-StackDeploy, Test-DeploymentHealth
