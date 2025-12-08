#!/bin/bash

# FlareCloud Quick Start Script (Local Development)

set -e

echo "========================================"
echo "   FlareCloud - Local Setup"
echo "========================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed."
    exit 1
fi

echo "✓ Python is installed"
echo ""

# Venv
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment exists"
fi

# Install
echo ""
echo "Installing requirements..."
source venv/bin/activate
pip install -r requirements.txt
echo "✓ Requirements installed"

# Config
if [ ! -f .env ]; then
    echo ""
    echo "Creating .env file..."
    cp .env.example .env
    echo "✓ .env file created"
    echo "NOTE: Please edit .env and set DATABASE_URL, REDIS_URL and SECRET_KEY"
else
    echo "✓ .env file already exists"
fi

echo ""
echo "Applying database migrations..."
alembic upgrade head

echo ""
echo "========================================"
echo "   🎉 Setup Complete!"
echo "========================================"
echo ""
echo "To run the services, open 3 separate terminals and run:"
echo ""
echo "Terminal 1 (API):"
echo "  source venv/bin/activate"
echo "  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
echo ""
echo "Terminal 2 (DNS Server):"
echo "  source venv/bin/activate"
echo "  python3 -m app.dns_server"
echo ""
echo "Terminal 3 (Celery Worker + Beat):"
echo "  source venv/bin/activate"
echo "  celery -A app.tasks.celery_app worker --beat -l info"
echo ""
