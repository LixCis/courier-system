@echo off
REM ============================================================
REM AI-Enhanced Courier System - Quick Start Script
REM ============================================================
REM This script will:
REM   1. Create virtual environment (if needed)
REM   2. Activate virtual environment
REM   3. Run setup.py (install dependencies, init DB, start app)
REM ============================================================

echo.
echo ============================================================
echo   AI-Enhanced Courier System - Quick Start
echo ============================================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Please install Python 3.8 or higher from python.org
    echo.
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist ".venv\" (
    echo [1/3] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo       Virtual environment created successfully
    echo.
) else (
    echo [1/3] Virtual environment already exists
    echo.
)

REM Activate virtual environment
echo [2/3] Activating virtual environment...
call .venv\Scripts\activate
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment!
    pause
    exit /b 1
)
echo       Virtual environment activated
echo.

REM Run setup script
echo [3/3] Running setup wizard...
echo.
python setup.py

REM Keep window open if there was an error
if errorlevel 1 (
    echo.
    echo ============================================================
    echo Setup failed! Please check the errors above.
    echo ============================================================
    pause
)
