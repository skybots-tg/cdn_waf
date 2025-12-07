@echo off
REM CDN WAF Quick Start Script for Windows

echo ========================================
echo    CDN WAF - Quick Start Setup
echo ========================================
echo.

REM Check if Docker is installed
docker --version >nul 2>&1
if errorlevel 1 (
    echo X Docker is not installed. Please install Docker first.
    exit /b 1
)

docker-compose --version >nul 2>&1
if errorlevel 1 (
    echo X Docker Compose is not installed. Please install Docker Compose first.
    exit /b 1
)

echo √ Docker and Docker Compose are installed
echo.

REM Copy .env.example to .env if not exists
if not exist .env (
    echo Creating .env file...
    copy .env.example .env
    echo √ .env file created
    echo NOTE: Please edit .env and set SECRET_KEY and JWT_SECRET_KEY
) else (
    echo √ .env file already exists
)

echo.
echo Starting services with Docker Compose...
docker-compose up -d

echo.
echo Waiting for services to be ready...
timeout /t 10 /nobreak >nul

echo.
echo Applying database migrations...
docker-compose exec -T app alembic upgrade head

echo.
echo ========================================
echo    Setup Complete!
echo ========================================
echo.
echo Services:
echo   API:        http://localhost:8000
echo   API Docs:   http://localhost:8000/docs
echo   Flower:     http://localhost:5555
echo.
echo Next steps:
echo   1. Open http://localhost:8000 in your browser
echo   2. Create an account
echo   3. Add your first domain
echo.
echo Useful commands:
echo   View logs:      docker-compose logs -f
echo   Stop services:  docker-compose down
echo   Restart:        docker-compose restart
echo.
pause

