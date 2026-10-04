@echo off
setlocal
cd /d "%~dp0"
set "MEIKIPOP_PYTHON=.venv-desktop\Scripts\pythonw.exe"
if not exist "%MEIKIPOP_PYTHON%" set "MEIKIPOP_PYTHON=.venv\Scripts\pythonw.exe"
if not exist "%MEIKIPOP_PYTHON%" (
    echo Meikipop needs its Python environment. See the project setup instructions.
    pause
    exit /b 1
)
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
start "" "%MEIKIPOP_PYTHON%" -m meikipop.scripts.quick_lookup %*
