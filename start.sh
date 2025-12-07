#!/bin/bash

# CDN WAF Quick Start Script
# This script helps you get started with CDN WAF quickly

set -e

echo "========================================"
echo "   CDN WAF - Quick Start Setup"
echo "========================================"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

echo "✓ Docker and Docker Compose are installed"
echo ""

# Copy .env.example to .env if not exists
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cp .env.example .env
    
    # Generate random secrets
    SECRET_KEY=$(openssl rand -hex 32)
    JWT_SECRET_KEY=$(openssl rand -hex 32)
    
    # Update .env with random secrets
    sed -i "s/SECRET_KEY=.*/SECRET_KEY=$SECRET_KEY/" .env
    sed -i "s/JWT_SECRET_KEY=.*/JWT_SECRET_KEY=$JWT_SECRET_KEY/" .env
    
    echo "✓ .env file created with random secrets"
else
    echo "✓ .env file already exists"
fi

echo ""
echo "Starting services with Docker Compose..."
docker-compose up -d

echo ""
echo "Waiting for services to be ready..."
sleep 10

echo ""
echo "Applying database migrations..."
docker-compose exec -T app alembic upgrade head

echo ""
echo "========================================"
echo "   🎉 Setup Complete!"
echo "========================================"
echo ""
echo "Services:"
echo "  📡 API:        http://localhost:8000"
echo "  📚 API Docs:   http://localhost:8000/docs"
echo "  🌸 Flower:     http://localhost:5555"
echo ""
echo "Next steps:"
echo "  1. Open http://localhost:8000 in your browser"
echo "  2. Create an account"
echo "  3. Add your first domain"
echo ""
echo "Useful commands:"
echo "  View logs:      docker-compose logs -f"
echo "  Stop services:  docker-compose down"
echo "  Restart:        docker-compose restart"
echo ""

