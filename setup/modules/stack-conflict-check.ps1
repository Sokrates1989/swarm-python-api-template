# Stack conflict check module

function Test-StackConflict {
    param(
        [Parameter(Mandatory=$true)]
        [string]$StackName
    )
    
    Write-Host ""
    Write-Host "🔍 Checking for existing stack..." -ForegroundColor Cyan
    
    $existingStack = docker stack ls --format "{{.Name}}" | Where-Object { $_ -eq $StackName }
    
    if ($existingStack) {
        Write-Host "⚠️  WARNING: Stack '$StackName' is already running!" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "This may interfere with deployment or secret updates."
        Write-Host "Secrets cannot be updated while they are in use by a running stack."
        Write-Host ""
        
        $removeStack = Read-Host "Remove existing stack before continuing? (y/N)"
        
        if ($removeStack -match '^[Yy]$') {
            Write-Host ""
            Write-Host "Removing stack: $StackName" -ForegroundColor Yellow
            docker stack rm $StackName
            
            Write-Host "Waiting for stack to be fully removed..." -ForegroundColor Yellow
            # Wait for services to be removed
            Start-Sleep -Seconds 2
            while (docker stack ls --format "{{.Name}}" | Where-Object { $_ -eq $StackName }) {
                Write-Host -NoNewline "."
                Start-Sleep -Seconds 2
            }
            Write-Host ""
            Write-Host "✅ Stack removed successfully" -ForegroundColor Green
            Write-Host ""
            return $true
        }
        else {
            Write-Host ""
            Write-Host "⚠️  Continuing with existing stack running." -ForegroundColor Yellow
            Write-Host "Note: You may encounter errors when creating/updating secrets."
            Write-Host ""
            return $false
        }
    }
    else {
        Write-Host "✅ No conflicting stack found" -ForegroundColor Green
        Write-Host ""
        return $true
    }
}
