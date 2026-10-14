@echo off
rem ============================================================
rem  Vocal Extractor - drag & drop audio files onto this file
rem  Creates two files next to each source audio file.
rem  Chinese filenames are produced by Python (UTF-8), never
rem  by this file, which stays pure ASCII for cmd.exe safety.
rem ============================================================
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if "%~1"=="" (
  echo.
  echo   ============================================
  echo    Vocal Extractor  /  Local vocal separation
  echo   ============================================
  echo.
  echo    How to use:
  echo      1. Drag one or more audio files onto this .bat
  echo      2. Or drag a whole folder onto it
  echo      3. Wait for it to finish
  echo.
  echo    Output: two files created next to each source
  echo    file - one with vocals only, one instrumental.
  echo    Exact filenames are listed after processing.
  echo.
  echo   ============================================
  echo.
  pause
  exit /b 0
)

if not exist "%~dp0.venv\Scripts\python.exe" (
  echo.
  echo   [ERROR] Virtual environment not found: .venv
  echo           Please follow the setup steps in README.md
  echo.
  pause
  exit /b 1
)

if not exist "%~dp0models" mkdir "%~dp0models" 2>nul

echo.
echo   Processing... please wait.
echo.

"%~dp0.venv\Scripts\python.exe" "%~dp0vocal_extractor.py" %* ^
  -q best-single ^
  -s Vocals,Instrumental ^
  --beside ^
  --model-dir "%~dp0models"

set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo   ============================================
  echo    DONE. Generated files are listed above,
  echo    saved next to each source audio file.
  echo   ============================================
) else (
  echo   [FAILED] Exit code %RC% - see log above.
)

echo.
pause
exit /b %RC%