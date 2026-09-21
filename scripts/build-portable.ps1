$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "请先运行 install-windows.ps1" }
& $python -m pip install pyinstaller
# 注意：PaddleOCR 模型仍在首次运行时下载到用户缓存；此脚本打包的是应用与Python依赖。
& $python -m PyInstaller --noconfirm --clean --onedir --name ClinicalExtractor `
  --add-data "templates;templates" --add-data "static;static" --add-data "profiles;profiles" `
  --collect-all langextract --collect-all paddleocr --collect-all paddlex `
  run_app.py
Write-Host "完成：dist\ClinicalExtractor" -ForegroundColor Green
