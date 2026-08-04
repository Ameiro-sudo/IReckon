@echo off
chcp 65001 >nul
title IReckon AI Factory
cls
echo ╔══════════════════════════════════════════════╗
echo ║        IReckon AI Factory  v0.1.0           ║
║    俺寻思 AI 工厂 - 多智能体自主编程系统    ║
echo ╚══════════════════════════════════════════════╝
echo.
echo [1/3] Starting backend...
start "" /min "%~dp0ireckon-backend\ireckon-backend.exe"
if %errorlevel% neq 0 (
    echo [!] Backend failed to start
    pause
    exit /b 1
)
timeout /t 3 /nobreak >nul

echo [2/3] Starting frontend...
start "" /min "%~dp0ireckon-frontend\ireckon-frontend.exe"
timeout /t 5 /nobreak >nul

cls
echo ╔══════════════════════════════════════════════╗
echo ║              Service Started!                ║
echo ╠══════════════════════════════════════════════╣
echo ║                                              ║
echo ║  Backend API     http://localhost:8000       ║
echo ║  API Docs        http://localhost:8000/docs  ║
echo ║  Frontend UI     http://localhost:8501       ║
echo ║                                              ║
echo ╠══════════════════════════════════════════════╣
echo ║  Close this window to stop all services      ║
echo ╚══════════════════════════════════════════════╝
echo.
start http://localhost:8501
pause >nul

echo Stopping services...
taskkill /f /im ireckon-backend.exe >nul 2>&1
taskkill /f /im ireckon-frontend.exe >nul 2>&1
echo Done.
