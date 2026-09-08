@echo off
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Install the project environment first. See docs\TURKISH_SETUP.md.
    pause
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" -m meikipop.scripts.turkish_desktop
