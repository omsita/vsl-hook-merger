@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo   VSL Hook Merger - First-Time Setup
echo ============================================
echo.

set "PY_OK="
set "TK_OK="
set "FFMPEG_OK="
set "FFPROBE_OK="
set "HAS_WINGET="

REM Detect winget availability up-front
where winget >nul 2>&1
if %errorlevel% equ 0 set "HAS_WINGET=1"

REM ---- [1/4] Python ------------------------------------------------------
echo [1/4] Checking Python...
where python >nul 2>&1
if %errorlevel% equ 0 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   [OK] Python %%v
        set "PY_OK=1"
    ) else (
        for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo   [X]  Python %%v is too old, need 3.10+
    )
) else (
    echo   [X]  Python not found on PATH.
)

if not defined PY_OK (
    if defined HAS_WINGET (
        echo.
        echo   Installing Python 3.12 via winget...
        winget install --id Python.Python.3.12 -e --silent --accept-source-agreements --accept-package-agreements
        if !errorlevel! equ 0 (
            echo.
            echo   Python installed. PATH was updated for new shells.
            echo   ^>^>^> Please CLOSE this window and run setup.bat again. ^<^<^<
            pause
            exit /b 0
        ) else (
            echo   winget install failed.
        )
    )
    echo.
    echo   Install Python manually from:
    echo     https://www.python.org/downloads/
    echo   IMPORTANT: tick "Add python.exe to PATH" during install.
    echo   Then re-run setup.bat.
    pause
    exit /b 1
)

REM ---- [2/4] tkinter -----------------------------------------------------
echo.
echo [2/4] Checking tkinter ^(GUI library^)...
python -c "import tkinter" >nul 2>&1
if %errorlevel% equ 0 (
    echo   [OK] tkinter available
    set "TK_OK=1"
) else (
    echo   [X]  tkinter NOT available in this Python.
    echo        Microsoft Store Python often lacks tkinter.
    echo        Install from https://www.python.org/downloads/ instead.
)

REM ---- [3/4] FFmpeg ------------------------------------------------------
echo.
echo [3/4] Checking FFmpeg...
where ffmpeg >nul 2>&1
if %errorlevel% equ 0 (
    ffmpeg -version >nul 2>&1
    if !errorlevel! equ 0 (
        echo   [OK] ffmpeg runs
        set "FFMPEG_OK=1"
    ) else (
        echo   [X]  ffmpeg on PATH but failed to execute.
    )
) else (
    echo   [X]  ffmpeg not found on PATH.
)

if not defined FFMPEG_OK (
    if defined HAS_WINGET (
        echo.
        echo   Installing FFmpeg ^(Gyan build^) via winget...
        winget install --id Gyan.FFmpeg -e --silent --accept-source-agreements --accept-package-agreements
        if !errorlevel! equ 0 (
            echo.
            echo   FFmpeg installed. PATH was updated for new shells.
            echo   ^>^>^> Please CLOSE this window and run setup.bat again. ^<^<^<
            pause
            exit /b 0
        ) else (
            echo   winget install failed.
        )
    )
    echo.
    echo   Install FFmpeg manually:
    echo     1. Download "release-full" from https://www.gyan.dev/ffmpeg/builds/
    echo     2. Extract to e.g. C:\ffmpeg
    echo     3. Add C:\ffmpeg\bin to PATH ^(System Environment Variables^)
    echo     4. Re-run setup.bat
)

REM ---- [4/4] ffprobe -----------------------------------------------------
echo.
echo [4/4] Checking ffprobe...
where ffprobe >nul 2>&1
if %errorlevel% equ 0 (
    ffprobe -version >nul 2>&1
    if !errorlevel! equ 0 (
        echo   [OK] ffprobe runs
        set "FFPROBE_OK=1"
    ) else (
        echo   [X]  ffprobe on PATH but failed to execute.
    )
) else (
    echo   [X]  ffprobe not found. Usually ships next to ffmpeg.
)

REM ---- Optional smoke test ------------------------------------------------
if defined PY_OK if defined TK_OK (
    echo.
    echo Running tkinter smoke test...
    python -c "import tkinter as t; r=t.Tk(); r.withdraw(); r.after(100,r.destroy); r.mainloop(); print('  [OK] tkinter window can spawn')"
)

REM ---- Summary -----------------------------------------------------------
echo.
echo ============================================
echo   Setup Result
echo ============================================
if defined PY_OK      (echo   [OK] Python 3.10+) else echo   [X]  Python 3.10+
if defined TK_OK      (echo   [OK] tkinter)      else echo   [X]  tkinter
if defined FFMPEG_OK  (echo   [OK] ffmpeg)       else echo   [X]  ffmpeg
if defined FFPROBE_OK (echo   [OK] ffprobe)      else echo   [X]  ffprobe

if defined PY_OK if defined TK_OK if defined FFMPEG_OK if defined FFPROBE_OK (
    echo.
    echo All set. Launch the tool with:
    echo     run.bat
    echo or:
    echo     python vsl_hook_merger.py
    echo.
    pause
    exit /b 0
) else (
    echo.
    echo Some prerequisites are missing. Fix the items marked [X] above and re-run setup.bat.
    echo.
    pause
    exit /b 1
)
