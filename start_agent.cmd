@echo off
setlocal
set REPO_ROOT=%~dp0
powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%REPO_ROOT%desktop_app.ps1"
