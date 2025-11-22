@echo off
echo ============================================================
echo Courier System MVP - Quick Start
echo ============================================================
echo.

REM Check if virtual environment exists
if not exist ".venv\" (
    echo Virtual environment not found. Creating...
    python -m venv .venv
)

REM Activate virtual environment
call .venv\Scripts\activate

REM Run setup script
python setup.py

pause
