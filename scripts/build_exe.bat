@echo off
REM Build IReckon Windows Executable

echo Building IReckon.exe...
pyinstaller build_exe.spec --clean
if %errorlevel% neq 0 (
    echo Build failed!
    exit /b %errorlevel%
)
echo.
echo Build complete! Executable is in dist folder.
pause