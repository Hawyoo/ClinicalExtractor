$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Invoke-Checked {
    param([scriptblock]$Command, [string]$Description)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed (exit code $LASTEXITCODE)."
    }
}

Write-Host "=== ClinicalExtractor installer ===" -ForegroundColor Cyan

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was not found. Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
}

# The project owns its interpreter. CPython 3.12 has broad, proven Windows
# wheel coverage across PaddleOCR and document-parser dependencies.
Invoke-Checked { uv python install 3.12 } "Python provisioning"
$python = Join-Path $PWD ".venv\Scripts\python.exe"
if (Test-Path $python) {
    # Do not rebuild a healthy environment on every launch. This also avoids
    # replacing files while the app is open.
    & $python -c "import pip"
    if ($LASTEXITCODE -ne 0) {
        Invoke-Checked { uv venv --clear --seed --python 3.12 .venv } "Virtual-environment repair"
    }
} else {
    Invoke-Checked { uv venv --seed --python 3.12 .venv } "Virtual-environment creation"
}

Invoke-Checked { uv pip install --python $python -e ".[ocr,dev]" } "Dependency installation"

Invoke-Checked { & $python -c "import paddle; print('PaddlePaddle', paddle.__version__); paddle.utils.run_check()" } "PaddlePaddle verification"
Invoke-Checked { & $python -c "from paddleocr import PPStructureV3; print('PP-StructureV3 import OK')" } "PP-StructureV3 verification"

Write-Host "Installation complete. Pull an Ollama model, then run start-windows.bat." -ForegroundColor Green
Write-Host "Example: ollama pull qwen3:8b"
