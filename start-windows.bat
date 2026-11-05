@echo off
setlocal
cd /d "%~dp0"
set "UV_CACHE_DIR=%CD%\.uv-cache"

where uv >nul 2>nul
if errorlevel 1 (
  echo [ERROR] uv was not found. Install it from https://docs.astral.sh/uv/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Downloading project Python 3.12...
  uv python install 3.12
  if errorlevel 1 goto :error
  echo [2/3] Creating the project environment...
  uv venv --seed --python 3.12 .venv
  if errorlevel 1 goto :error
  ) else (
  echo [1/3] Project Python is ready.
)

echo [3/3] Checking ClinicalExtractor dependencies...
uv pip install --python ".venv\Scripts\python.exe" -e ".[ocr,dev]"
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -c "import paddle; from paddleocr import PPStructureV3; import langextract"
if errorlevel 1 goto :error

if /i "%~1"=="--prepare" exit /b 0

powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 http://127.0.0.1:8765/health ^| Out-Null; exit 0 } catch { exit 1 }"
if not errorlevel 1 (
  echo ClinicalExtractor is already running. Opening the browser...
  start "" http://127.0.0.1:8765
  exit /b 0
)

for /f %%P in ('powershell -NoProfile -Command "$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,8765); try { $listener.Start(); $listener.Stop(); 8765 } catch { $fallback = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback,0); $fallback.Start(); $port = $fallback.LocalEndpoint.Port; $fallback.Stop(); $port }"') do set "CLINICAL_EXTRACTOR_PORT=%%P"
if not defined CLINICAL_EXTRACTOR_PORT goto :error
echo Starting ClinicalExtractor at http://127.0.0.1:%CLINICAL_EXTRACTOR_PORT% ...
start "" http://127.0.0.1:%CLINICAL_EXTRACTOR_PORT%
".venv\Scripts\python.exe" -m clinical_extractor.main
set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] ClinicalExtractor stopped unexpectedly. Exit code: %APP_EXIT_CODE%
  echo Check logs\ocr-worker.log for native OCR faults.
  pause
  exit /b %APP_EXIT_CODE%
)
exit /b 0

:error
echo.
echo [ERROR] Startup preparation failed. Keep this window open and copy the error above.
pause
exit /b 1
