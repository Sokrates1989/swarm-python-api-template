# Stack deployment module

function Invoke-StackDeploy {
    <#
    .SYNOPSIS
    Deploys the stack by rendering the compose file and running docker stack deploy.

    .DESCRIPTION
    Uses docker-compose or the Docker Compose plugin (docker compose) to render the stack file with
    environment variable interpolation from the adjacent .env file, then deploys the rendered config.

    .OUTPUTS
    System.Boolean
    #>
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
    
    # Check for existing stack and offer to remove it
    Test-StackConflict -StackName $StackName
    
    $ConfirmDeploy = Read-Host "Deploy now? (Y/n)"
    if ($ConfirmDeploy -eq "n" -or $ConfirmDeploy -eq "N") {
        Write-Host "Deployment cancelled."
        return $false
    }
    
    
    Write-Host ""
    Write-Host "Deploying stack..."
    
    # Resolve paths and env file
    $stackFileFull = (Resolve-Path $StackFile).Path
    $envFile = Join-Path (Split-Path -Parent $stackFileFull) ".env"
    
    # Generate config and deploy (PowerShell doesn't support process substitution)
    $tempConfig = [System.IO.Path]::GetTempFileName()

    $renderExit = 1
    $composeCmd = $null
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        $composeCmd = @("docker-compose")
    } else {
        docker compose version 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ Neither docker-compose nor 'docker compose' is available" -ForegroundColor Red
            Remove-Item $tempConfig -ErrorAction SilentlyContinue
            return $false
        }
        $composeCmd = @("docker", "compose")
    }

    $prefixArgs = @()
    if ($composeCmd.Count -gt 1) {
        $prefixArgs = $composeCmd[1..($composeCmd.Count - 1)]
    }

    $envArgs = @()
    if ((Test-Path $envFile)) {
        $helpText = & $composeCmd[0] @($prefixArgs + @("--help")) 2>$null
        if ($helpText -match "--env-file") {
            $envArgs = @("--env-file", $envFile)
        }
    }

    & $composeCmd[0] @($prefixArgs + @("-f", $stackFileFull) + $envArgs + @("config")) | Out-File -FilePath $tempConfig -Encoding utf8
    $renderExit = $LASTEXITCODE

    if ($renderExit -ne 0) {
        Write-Host "❌ Failed to render config" -ForegroundColor Red
        Remove-Item $tempConfig -ErrorAction SilentlyContinue
        return $false
    }

    docker stack deploy -c $tempConfig $StackName
    Remove-Item $tempConfig -ErrorAction SilentlyContinue
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Deployment failed" -ForegroundColor Red
        return $false
    }
    
    Write-Host ""
    Write-Host "✅ Stack deployed successfully" -ForegroundColor Green
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
    Write-Host "💡 Tip: Run health checks with the health-check.ps1 module" -ForegroundColor Cyan
    Write-Host ""
    
    return $true
}

Export-ModuleMember -Function Invoke-StackDeploy
