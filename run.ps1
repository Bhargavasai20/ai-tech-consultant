# One command to run all three tasks on Windows PowerShell (mock mode, no API key needed).
# Usage, from the project root:   .\run.ps1
# Real mode: set $env:ANTHROPIC_API_KEY first and the mock flags are skipped.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py   = Join-Path $root ".venv\Scripts\python.exe"
$url  = "http://127.0.0.1:8001"

if (-not (Test-Path $py)) {
    Write-Host "No .venv found. Create it first:  py -3.12 -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -e task1_brain -e task3_scope" -ForegroundColor Red
    exit 1
}

$mock = [string]::IsNullOrEmpty($env:ANTHROPIC_API_KEY)
$flags = ""
if ($mock) {
    $flags = '$env:BRAIN_MOCK="1"; $env:INBOX_MOCK="1"; $env:SCOPE_MOCK="1"; '
    Write-Host ">> MOCK mode (no ANTHROPIC_API_KEY): shows wiring, not model quality"
}

# Task 2 needs its npm packages once.
if (-not (Test-Path (Join-Path $root "task2_inbox\node_modules"))) {
    Write-Host ">> Installing Task 2 packages (first run only)..."
    Push-Location (Join-Path $root "task2_inbox"); npm install; Pop-Location
}

# Load demo data for Task 1 (mock mode only).
if ($mock) {
    Push-Location (Join-Path $root "task1_brain")
    $env:BRAIN_MOCK = "1"
    & $py -m brain.cli demo | Out-Null
    Pop-Location
}

function Start-Service($title, $dir, $cmd) {
    $full = "`$Host.UI.RawUI.WindowTitle='$title'; $flags`$env:BRAIN_URL='$url'; Set-Location '$dir'; $cmd"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $full
}

Start-Service "Task 1 Brain"  (Join-Path $root "task1_brain") "& '$py' -m brain.cli serve --port 8001"
Start-Sleep -Seconds 3
Start-Service "Task 2 Inbox"  (Join-Path $root "task2_inbox") "node src/server.ts"
Start-Service "Task 3 Scope"  (Join-Path $root "task3_scope") "& '$py' -m scope.cli serve"
Start-Sleep -Seconds 3

Write-Host ">> Task 1 Knowledge Brain  http://127.0.0.1:8001   (API docs: /docs)"
Write-Host ">> Task 2 Inbox Agent      http://127.0.0.1:8002"
Write-Host ">> Task 3 Scope of Work    http://127.0.0.1:8003"
Write-Host ">> Close the three new windows to stop everything."
Start-Process "http://127.0.0.1:8001"
