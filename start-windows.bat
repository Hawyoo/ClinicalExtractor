@echo off
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo 尚未安装环境，正在启动安装脚本...
  powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
  if errorlevel 1 pause & exit /b 1
)
start "" http://127.0.0.1:8765
.venv\Scripts\python.exe -m clinical_extractor.main
pause
