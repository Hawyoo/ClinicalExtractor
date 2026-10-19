@echo off
setlocal
cd /d "%~dp0"
set "UV_CACHE_DIR=%CD%\.uv-cache"

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
set "PORTABLE=dist\ClinicalExtractor"
if not exist "%PORTABLE%\data\uploads" mkdir "%PORTABLE%\data\uploads"
if not exist "%PORTABLE%\data\exports" mkdir "%PORTABLE%\data\exports"
if not exist "%PORTABLE%\logs" mkdir "%PORTABLE%\logs"
if not exist "%PORTABLE%\models\paddlex-cache" mkdir "%PORTABLE%\models\paddlex-cache"
if not exist ".portable-model-cache\official_models" goto :model_error
xcopy /E /I /Y ".portable-model-cache\official_models" "%PORTABLE%\models\paddlex-cache\official_models\" >nul
if errorlevel 2 goto :error
copy /Y "docs\WINDOWS_PORTABLE.md" "%PORTABLE%\WINDOWS_PORTABLE.md" >nul
copy /Y "scripts\portable-startup.ps1" "%PORTABLE%\portable-startup.ps1" >nul
copy /Y "scripts\Start-ClinicalExtractor.bat" "%PORTABLE%\Start-ClinicalExtractor.bat" >nul
copy /Y "static\clinical-extractor.ico" "%PORTABLE%\clinical-extractor.ico" >nul

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
