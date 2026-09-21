$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "=== ClinicalExtractor Windows Installer ===" -ForegroundColor Cyan
$py = $null
foreach ($cmd in @("py -3.11", "py -3.10", "python")) {
  try { Invoke-Expression "$cmd --version" | Out-Host; $py=$cmd; break } catch {}
}
if (-not $py) { throw "需要 Python 3.10/3.11。建议安装 Python 3.11 x64 后重试。" }

if (-not (Test-Path ".venv")) { Invoke-Expression "$py -m venv .venv" }
$python = Join-Path $PWD ".venv\Scripts\python.exe"
& $python -m pip install -U pip wheel setuptools

# PaddlePaddle CPU inference engine; AMD Windows machines use CPU for PP-StructureV3 by default.
& $python -m pip install paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
& $python -m pip install -e ".[ocr]"

Write-Host "安装完成。请确保 Ollama 已安装并已拉取模型，然后双击 start-windows.bat。" -ForegroundColor Green
Write-Host "示例: ollama pull qwen3:8b"
