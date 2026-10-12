@echo off
set PYTHON_EXE=..\environments\Python311\python.exe
set MAIN_SCRIPT=main.py

:loop
echo [%date% %time%] Starting %MAIN_SCRIPT%...

if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%MAIN_SCRIPT%"
) else if exist "venv\Scripts\activate.bat" (
    pushd venv\Scripts
    call activate.bat
    popd
    python %MAIN_SCRIPT%
) else (
    python %MAIN_SCRIPT%
)

set EXIT_CODE=%ERRORLEVEL%
echo [%date% %time%] Exit code: %EXIT_CODE%

if %EXIT_CODE% == 0 (
    echo [%date% %time%] Script exited normally. Stopping.
    exit /b 0
)
if %EXIT_CODE% == 77 (
    echo [%date% %time%] Restart handled externally. Stopping loop.
    exit /b 0
)

echo [%date% %time%] Script crashed with code %EXIT_CODE%. Restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto loop
