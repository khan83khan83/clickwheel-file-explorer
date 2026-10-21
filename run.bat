@echo off
rem Launch Clickwheel File Explorer with no console window. Double-click this file.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" main.py
