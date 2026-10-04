$ErrorActionPreference = "Stop"
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  Write-Host "No .venv found. Create it first: py -3.12 -m venv .venv" -ForegroundColor Yellow
  exit 1
}
& .\.venv\Scripts\python.exe -m uvicorn faq_service.app:app --host 127.0.0.1 --port 8011
