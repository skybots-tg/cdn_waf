@echo off
REM FlareCloud Quick Start Script for Windows (Local Development)

echo ========================================
echo    FlareCloud - Local Setup
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo X Python is not installed. Please install Python 3.10+ first.
    exit /b 1
)

echo √ Python is installed
echo.

REM Check for virtual environment
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
    echo √ Virtual environment created
) else (
    echo √ Virtual environment exists
)

REM Activate venv
call venv\Scripts\activate

REM Install requirements
echo.
echo Installing requirements...
pip install -r requirements.txt
echo √ Requirements installed

REM Copy .env.example to .env if not exists
if not exist .env (
    echo.
    echo Creating .env file...
    copy .env.example .env
    echo √ .env file created
    echo NOTE: Please edit .env and set DATABASE_URL, REDIS_URL and SECRET_KEY
) else (
    echo √ .env file already exists
)

echo.
echo Applying database migrations...
alembic upgrade head

echo.
echo ========================================
echo    Setup Complete!
echo ========================================
echo.
echo To run the services, open 3 separate terminals and run:
echo.
echo Terminal 1 (API):
echo   venv\Scripts\activate
echo   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
echo.
echo Terminal 2 (DNS Server):
echo   venv\Scripts\activate
echo   python -m app.dns_server
echo.
echo Terminal 3 (Celery Worker):
echo   venv\Scripts\activate
echo   celery -A app.tasks.celery_app worker -l info -P gevent
echo.
echo Useful:
echo   Run verification manually: python -c "from app.tasks.dns_tasks import verify_pending_domains; import asyncio; asyncio.run(verify_pending_domains())"
echo.
pause
