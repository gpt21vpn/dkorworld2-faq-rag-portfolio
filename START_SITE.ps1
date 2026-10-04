$ErrorActionPreference = "Stop"
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  Write-Host "No .venv found. Create it first: py -3.12 -m venv .venv" -ForegroundColor Yellow
  exit 1
}
$env:FAQ_RAG_URL = "http://127.0.0.1:8011"
& .\.venv\Scripts\python.exe app.py
