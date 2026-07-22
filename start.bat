@echo off
chcp 65001 >nul
title MediaDown

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found!
    pause
    exit /b 1
)

cd /d "%~dp0backend"

pip show flask >nul 2>&1
if %errorlevel% neq 0 (
    pip install -r requirements.txt -q
)

:: Kill old server processes
taskkill /f /im python.exe /fi "WINDOWTITLE eq MediaDown*" >nul 2>&1
taskkill /f /im pythonw.exe /fi "WINDOWTITLE eq MediaDown*" >nul 2>&1

:: Start server in background
start /min python app.py

:: Wait for server to start
ping -n 5 127.0.0.1 >nul

:: Find Chrome - try registry first, then common paths
set CHROME=
for /f "tokens=2*" %%a in ('reg query "HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe" /ve 2^>nul ^| find "REG_SZ"') do set CHROME=%%b
if not defined CHROME if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" set CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe
if not defined CHROME if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" set CHROME=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe

if defined CHROME (
    start "" "%CHROME%" --new-window http://localhost:5000
) else (
    start http://localhost:5000
)
