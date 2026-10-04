$ErrorActionPreference = 'Stop'

Write-Host '=== DKORWORLD2 DZ8: local Docker build ==='

docker compose build
if ($LASTEXITCODE -ne 0) { throw 'docker compose build failed' }

$image = 'dkorworld/dz8-site:12.3'
$out = Join-Path $PSScriptRoot 'dz8-site-image.tar'

if (Test-Path $out) { Remove-Item $out -Force }
docker save -o $out $image
if ($LASTEXITCODE -ne 0) { throw 'docker save failed' }

$item = Get-Item $out
$mb = [math]::Round($item.Length / 1MB, 1)
Write-Host "READY: $($item.FullName) ($mb MB)"
Write-Host 'Next: upload dz8-site-image.tar and docker-compose.yml to Cloud4box.'
