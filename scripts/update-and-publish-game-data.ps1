$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$snapshotRelative = "data/blueprints_snapshot.json"
$snapshotPath = Join-Path $projectRoot $snapshotRelative
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$importerPath = Join-Path $projectRoot "scripts\update_game_data_from_p4k.py"
$gameArchive = "C:\StarCitizen\LIVE\Data.p4k"
$productionStatusUrl = "https://sccompanion.org/api/game-data/status"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Program,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed with exit code $LASTEXITCODE."
    }
}

Write-Host ""
Write-Host "STAR CITIZEN MISSION + BLUEPRINT UPDATE" -ForegroundColor Cyan
Write-Host "This publishes data from your installed LIVE game files." -ForegroundColor DarkGray

foreach ($requiredPath in @($gameArchive, $pythonPath, $importerPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Required file not found: $requiredPath"
    }
}

Push-Location $projectRoot
try {
    $branch = (& git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0 -or $branch -ne "main") {
        throw "Open the project on the main branch before running the updater."
    }
    $trackedChanges = @(& git status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) {
        throw "The project status could not be checked."
    }
    if ($trackedChanges.Count -gt 0) {
        throw "The project has other unfinished changes. Finish or set them aside before updating game data."
    }

    Write-Host ""
    Write-Host "1/5  Checking for the latest project version..."
    Invoke-Checked git pull --ff-only origin main

    Write-Host ""
    Write-Host "2/5  Reading Data.p4k and rebuilding the database..."
    Invoke-Checked $pythonPath $importerPath

    & git diff --quiet -- $snapshotRelative
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "The installed game data already matches the published snapshot." -ForegroundColor Green
        exit 0
    }
    if ($LASTEXITCODE -ne 1) {
        throw "The rebuilt snapshot could not be compared."
    }

    $snapshot = Get-Content -LiteralPath $snapshotPath -Raw | ConvertFrom-Json
    $version = [string]$snapshot.source.version
    if ([string]::IsNullOrWhiteSpace($version)) {
        throw "The rebuilt snapshot does not contain a game version."
    }

    Write-Host ""
    Write-Host "3/5  Running safety checks..."
    Invoke-Checked $pythonPath -m pytest -q

    Write-Host ""
    Write-Host "4/5  Publishing $version..."
    Invoke-Checked git add -- $snapshotRelative
    Invoke-Checked git commit -m "Update game data to $version" -- $snapshotRelative
    Invoke-Checked git push origin main

    Write-Host ""
    Write-Host "5/5  Waiting for the hosted website to confirm the update..."
    $deadline = (Get-Date).AddMinutes(20)
    $deployed = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $status = Invoke-RestMethod -Uri $productionStatusUrl -Method Get -TimeoutSec 20
            if ([string]$status.version -eq $version) {
                $deployed = $true
                Write-Host ""
                Write-Host "Update complete: $version" -ForegroundColor Green
                Write-Host "$($status.blueprints) blueprints and $($status.missions) missions are live."
                break
            }
        }
        catch {
            # The host can briefly be unavailable while the new release starts.
        }
        Start-Sleep -Seconds 10
    }
    if (-not $deployed) {
        throw "The data was pushed, but the hosted website did not confirm $version within 20 minutes."
    }
}
finally {
    Pop-Location
}
