# Network verification module
# Checks DNS resolution and confirms with user

function Network-Verify {
    param(
        [string]$ApiUrl,
        [string]$ProxyType
    )
    
    if ($ProxyType -eq "traefik") {
        Write-Host "🌐 Network Verification" -ForegroundColor Cyan
        Write-Host "======================"
        Write-Host ""
        Write-Host "Checking DNS resolution for: $ApiUrl"
        Write-Host ""
        
        # Try to resolve the domain
        try {
            $ResolvedIPs = [System.Net.Dns]::GetHostAddresses($ApiUrl)
            if ($ResolvedIPs.Count -gt 0) {
                $ResolvedIP = $ResolvedIPs[0].IPAddressToString
                Write-Host "✅ Domain resolves to: $ResolvedIP" -ForegroundColor Green
                Write-Host ""
                $ConfirmIP = Read-Host "Is this the correct IP for your swarm manager? (Y/n)"
                if ($ConfirmIP -eq "n" -or $ConfirmIP -eq "N") {
                    Write-Host ""
                    Write-Host "❌ DNS not configured correctly. Please update your DNS records:" -ForegroundColor Red
                    Write-Host "   Domain: $ApiUrl"
                    Write-Host "   Should point to: <your-swarm-manager-ip>"
                    Write-Host ""
                    Write-Host "After updating DNS, wait for propagation (can take up to 48 hours)"
                    Write-Host "and re-run the setup wizard."
                    return $false
                }
            }
        } catch {
            Write-Host "⚠️  Unable to resolve domain: $ApiUrl" -ForegroundColor Yellow
            Write-Host ""
            Write-Host "Please ensure:"
            Write-Host "  1. Domain is registered"
            Write-Host "  2. DNS A record points to your swarm manager IP"
            Write-Host "  3. DNS has propagated (can take up to 48 hours)"
            Write-Host ""
            $ContinueAnyway = Read-Host "Continue anyway? (y/N)"
            if ($ContinueAnyway -ne "y" -and $ContinueAnyway -ne "Y") {
                return $false
            }
        }
        Write-Host ""
    }
    
    return $true
}

Export-ModuleMember -Function Network-Verify
