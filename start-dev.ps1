# Starts LeaveDesk for development, each part in its own window:
#   1. the database (Docker), 2. the API (port 8000), 3. the website (port 4200).
#
# Run it from the leave-management folder:
#   powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
#
# Passwords and the port are read from backend\.env, so none are written here.

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

function Read-EnvValue([string]$name, [string]$default) {
    $line = Get-Content (Join-Path $backend '.env') | Where-Object { $_ -match "^$name=" } | Select-Object -First 1
    if ($line) { return ($line -split '=', 2)[1].Trim() } else { return $default }
}

$appPassword = Read-EnvValue 'LEAVEDESK_APP_DB_PASSWORD' ''
$port = Read-EnvValue 'POSTGRES_HOST_PORT' '5432'
if (-not $appPassword) { throw 'LEAVEDESK_APP_DB_PASSWORD is missing from backend\.env' }

Write-Host '1/3 Starting the database (Docker Desktop must be open)...'
Set-Location $backend
docker compose up -d db
if ($LASTEXITCODE -ne 0) { throw 'Docker did not start the database. Is Docker Desktop running?' }

$container = (docker compose ps -q db)
for ($i = 0; $i -lt 30; $i++) {
    $health = docker inspect --format '{{.State.Health.Status}}' $container
    if ($health -eq 'healthy') { break }
    Start-Sleep -Seconds 1
}
Write-Host "   database: $health (port $port)"

Write-Host '2/3 Starting the API in a new window (http://127.0.0.1:8000)...'
$apiCommand = @"
Set-Location '$backend'
.\.venv\Scripts\Activate.ps1
`$env:LEAVEDESK_DATABASE_URL = 'postgresql+pg8000://leavedesk_app:$appPassword@127.0.0.1:$port/leavedesk'
`$host.UI.RawUI.WindowTitle = 'LeaveDesk API - keep this window open'
python -m uvicorn leavedesk.api.main:create_app --factory --reload
"@
Start-Process powershell -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $apiCommand

Write-Host '3/3 Starting the website in a new window (http://localhost:4200)...'
$webCommand = @"
Set-Location '$frontend'
`$host.UI.RawUI.WindowTitle = 'LeaveDesk website - keep this window open'
npm start
"@
Start-Process powershell -ArgumentList '-NoExit', '-ExecutionPolicy', 'Bypass', '-Command', $webCommand

Set-Location $root
Write-Host ''
Write-Host 'Done. Wait about 20 seconds, then open http://localhost:4200'
Write-Host 'Sign in as asha@leavedesk.dev or ravi@leavedesk.dev with password demo1234.'
Write-Host 'To stop: close the two new windows (the database can keep running).'
