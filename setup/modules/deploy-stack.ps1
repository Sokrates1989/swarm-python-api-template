# Stack deployment module

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
    
    # Resolve paths and env file
    $stackFileFull = (Resolve-Path $StackFile).Path
    $envFile = Join-Path (Split-Path -Parent $stackFileFull) ".env"
    
    # Generate config and deploy (PowerShell doesn't support process substitution)
    $tempConfig = [System.IO.Path]::GetTempFileName()
    docker-compose -f $stackFileFull --env-file $envFile config | Out-File -FilePath $tempConfig -Encoding utf8
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
