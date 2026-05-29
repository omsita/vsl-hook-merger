@echo off
REM Double-click launcher. Picks the `python` on PATH.
cd /d "%~dp0"
python vsl_hook_merger.py
if errorlevel 1 pause
