@echo off
setlocal

cd /d "%~dp0"

echo [1/3] Installing dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [2/3] Building executable...
pyinstaller --clean --noconfirm sql_backup_tool.spec
if errorlevel 1 goto :error

echo [3/3] Build completed.
echo Output: %~dp0dist\SQLServerBackupTool.exe
goto :eof

:error
echo Build failed.
exit /b 1
