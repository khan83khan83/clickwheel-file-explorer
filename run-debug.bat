@echo off
rem Same app, but keeps a console open so errors and printed output are visible.
cd /d "%~dp0"
".venv\Scripts\python.exe" main.py
echo.
echo --- app exited (code %ERRORLEVEL%) ---
pause
