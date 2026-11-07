@echo off
setlocal
cd /d "%~dp0"
set "UV_CACHE_DIR=%CD%\.uv-cache"
set "PORTABLE=dist\ClinicalExtractor"
set "DATA_BACKUP=.portable-data-backup"

rem PyInstaller recreates dist. Preserve any real reports stored by a prior
rem Portable edition before the build removes that directory.
if exist "%DATA_BACKUP%" (
  echo [ERROR] A previous Portable data backup exists: %CD%\%DATA_BACKUP%
  echo Check it first, then rename or remove it before rebuilding.
  pause
  exit /b 1
)
if exist "%PORTABLE%\data" (
  echo Preserving existing Portable data...
  robocopy "%PORTABLE%\data" "%DATA_BACKUP%" /E /R:1 /W:1 >nul
  if errorlevel 8 goto :error
)

echo [1/5] Checking the source environment...
call "%~dp0start-windows.bat" --prepare
if errorlevel 1 goto :error

echo [2/5] Installing the packaging tool...
".venv\Scripts\python.exe" -m pip install "pyinstaller>=6.0"
if errorlevel 1 goto :error

echo [3/5] Downloading and preparing the offline OCR models...
set "PADDLE_PDX_CACHE_HOME=%CD%\.portable-model-cache"
".venv\Scripts\python.exe" scripts\warm-ocr-models.py
if errorlevel 1 goto :error

echo [4/5] Building the Windows Portable. This can take several minutes...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean ClinicalExtractor.spec
if errorlevel 1 goto :error

echo [5/5] Preparing Portable startup files and offline OCR cache...
if not exist "%PORTABLE%\data\uploads" mkdir "%PORTABLE%\data\uploads"
if not exist "%PORTABLE%\data\exports" mkdir "%PORTABLE%\data\exports"
if not exist "%PORTABLE%\logs" mkdir "%PORTABLE%\logs"
if not exist "%PORTABLE%\models\paddlex-cache" mkdir "%PORTABLE%\models\paddlex-cache"
if not exist ".portable-model-cache\official_models" goto :model_error
".venv\Scripts\python.exe" scripts\copy-portable-models.py ".portable-model-cache\official_models" "%PORTABLE%\models\paddlex-cache\official_models"
if errorlevel 1 goto :error
copy /Y "docs\WINDOWS_PORTABLE.md" "%PORTABLE%\WINDOWS_PORTABLE.md" >nul
copy /Y "LICENSE" "%PORTABLE%\LICENSE" >nul
copy /Y "THIRD_PARTY.md" "%PORTABLE%\THIRD_PARTY.md" >nul
copy /Y "scripts\portable-startup.ps1" "%PORTABLE%\portable-startup.ps1" >nul
copy /Y "static\clinical-extractor.ico" "%PORTABLE%\clinical-extractor.ico" >nul
if exist "%DATA_BACKUP%" (
  echo Restoring existing Portable data...
  robocopy "%DATA_BACKUP%" "%PORTABLE%\data" /E /R:1 /W:1 >nul
  if errorlevel 8 goto :error
  ".venv\Scripts\python.exe" scripts\archive-build-backup.py
  if errorlevel 1 goto :error
)

echo.
echo Done: %CD%\%PORTABLE%\ClinicalExtractor.exe
echo Double-click ClinicalExtractor.exe to run the Portable edition.
pause
exit /b 0

:model_error
echo.
echo [ERROR] The offline OCR model cache was not created.
echo Please keep internet access enabled during step 3 and run this BAT again.
pause
exit /b 1

:error
echo.
echo [ERROR] Portable build failed. Keep this window open and copy the error above.
pause
exit /b 1
