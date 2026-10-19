$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\install-windows.ps1"
    if ($LASTEXITCODE -ne 0) { throw "Project dependency installation failed." }
}
$python = Join-Path $PWD ".venv\Scripts\python.exe"
& $python -m pip install "pyinstaller>=6.0"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed." }

Write-Host "Building ClinicalExtractor (the first build can take several minutes)..." -ForegroundColor Cyan
& $python -m PyInstaller --noconfirm --clean ClinicalExtractor.spec
if ($LASTEXITCODE -ne 0) { throw "Portable build failed." }

$portable = Join-Path $PWD "dist\ClinicalExtractor"
@("data\uploads", "data\exports", "logs", "models\paddlex-cache") | ForEach-Object {
    New-Item -ItemType Directory -Force -Path (Join-Path $portable $_) | Out-Null
}
Copy-Item -LiteralPath "docs\WINDOWS_PORTABLE.md" -Destination (Join-Path $portable "WINDOWS_PORTABLE.md") -Force
Copy-Item -LiteralPath "scripts\portable-startup.ps1" -Destination (Join-Path $portable "portable-startup.ps1") -Force
Copy-Item -LiteralPath "scripts\Start-ClinicalExtractor.bat" -Destination (Join-Path $portable "Start-ClinicalExtractor.bat") -Force
Copy-Item -LiteralPath "static\clinical-extractor.ico" -Destination (Join-Path $portable "clinical-extractor.ico") -Force
Write-Host "Portable created: $portable\ClinicalExtractor.exe" -ForegroundColor Green
