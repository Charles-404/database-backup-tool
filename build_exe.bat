@echo off
setlocal

cd /d "%~dp0"

set "PYTHONNOUSERSITE=1"
set "PYTHONUSERBASE=%~dp0.userbase"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [0/3] Creating virtual environment...
    python -m venv "%~dp0.venv"
    if errorlevel 1 goto :error
)

echo [1/3] Installing dependencies...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [2/3] Building executable...
"%VENV_PY%" -m PyInstaller --clean --noconfirm sql_backup_tool.spec
if errorlevel 1 goto :error

echo [3/3] Build completed.
echo Output: %~dp0dist\SQLServerBackupTool.exe
goto :eof

:error
echo Build failed.
exit /b 1
