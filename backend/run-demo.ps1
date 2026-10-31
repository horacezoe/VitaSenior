# Start the demo server with the local secrets from backend/.env.
#
#   .\run-demo.ps1              # port 8000
#   .\run-demo.ps1 -Port 8010   # another port
#
# The application itself never auto-loads .env (that would make pytest depend on
# local secrets); this script exports the file into the process environment and
# then starts uvicorn, which inherits it. Missing keys fail loudly.
param([int]$Port = 8000)

$ErrorActionPreference = 'Stop'
$envFile = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $envFile)) {
    throw "Missing backend/.env - copy *.env.example and fill in your own credentials."
}

$loaded = 0
foreach ($line in Get-Content $envFile -Encoding UTF8) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
    $parts = $trimmed -split '=', 2
    if ($parts.Count -lt 2) { continue }
    [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), 'Process')
    $loaded++
}

$providers = "chat=$env:CHAT_PROVIDER asr=$env:ASR_PROVIDER tts=$env:TTS_PROVIDER"
# Media content_url is built from PUBLIC_BASE_URL; if it points at another port the
# <img>/<audio> URLs would hit a dead port. Keep it aligned with the served port.
if ($env:PUBLIC_BASE_URL -match '^(https?://[^/:]+)(:\d+)?/?$') {
    $env:PUBLIC_BASE_URL = "$($Matches[1]):$Port"
}
Write-Host "loaded $loaded variables from backend/.env (providers: $providers)"
Write-Host "public base url: $env:PUBLIC_BASE_URL"
Write-Host "starting uvicorn on http://0.0.0.0:$Port  (docs: /docs)"
Push-Location $PSScriptRoot
try {
    & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m uvicorn app.main:app --host 0.0.0.0 --port $Port --workers 1
}
finally {
    Pop-Location
}
