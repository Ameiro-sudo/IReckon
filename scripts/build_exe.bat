@echo off
REM Build IReckon Windows Executable
REM 统一构建入口：委托给 scripts/build_exe.py（与 CI build.yml 同一条构建管线）

echo Building IReckon.exe...
python scripts/build_exe.py
if %errorlevel% neq 0 (
    echo Build failed!
    exit /b %errorlevel%
)
echo.
echo Build complete! Executable is in dist folder.
pause