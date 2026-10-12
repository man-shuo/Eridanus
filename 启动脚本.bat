@echo off
set PYTHON_EXE=..\environments\Python311\python.exe
set MAIN_SCRIPT=main.py

rem checking.....
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

if %ERRORLEVEL% equ 0 exit /b 0
if %ERRORLEVEL% equ 77 exit /b 0
pause
