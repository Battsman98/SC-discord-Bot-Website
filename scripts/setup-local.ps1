param(
    [string]$VenvPath = ".venv"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python is not installed or not on PATH. Install Python 3.12+ from https://www.python.org/downloads/windows/ and rerun this script."
}

if (-not (Test-Path $VenvPath)) {
    python -m venv $VenvPath
}

& "$VenvPath\Scripts\python.exe" -m pip install --upgrade pip
& "$VenvPath\Scripts\pip.exe" install -r requirements-dev.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Add your DISCORD_TOKEN before running the bot."
}

Write-Host "Local setup complete."
Write-Host "Activate with: .\$VenvPath\Scripts\Activate.ps1"
Write-Host "Run with: python -m src.bot"
