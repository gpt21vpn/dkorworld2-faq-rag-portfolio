$ErrorActionPreference = "Stop"
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
  Write-Host "No .venv found. Create it first: py -3.12 -m venv .venv" -ForegroundColor Yellow
  exit 1
}
& .\.venv\Scripts\python.exe -m faq_service.build_index
