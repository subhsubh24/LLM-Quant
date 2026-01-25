#!/bin/bash

# QuantLab Demo Runner
# This script sets up and runs both backend and frontend

set -e

echo "=========================================="
echo "  QuantLab - Quant Research Platform"
echo "=========================================="
echo ""
echo "DISCLAIMER: This is an educational paper trading"
echo "simulation. Not financial advice."
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

# Check Node
if ! command -v node &> /dev/null; then
    echo "Error: Node.js is required but not installed."
    exit 1
fi

# Setup backend
echo "Setting up backend..."
cd "$(dirname "$0")/../backend"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
    cp .env.example .env
fi

# Start backend in background
echo "Starting backend on http://localhost:8000..."
uvicorn app.api.main:app --port 8000 &
BACKEND_PID=$!

# Setup frontend
echo "Setting up frontend..."
cd "../frontend"

if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

if [ ! -f ".env" ]; then
    cp .env.example .env
fi

# Start frontend
echo "Starting frontend on http://localhost:3000..."
npm run dev &
FRONTEND_PID=$!

# Cleanup on exit
cleanup() {
    echo "Shutting down..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
}
trap cleanup EXIT

echo ""
echo "=========================================="
echo "  QuantLab is running!"
echo "=========================================="
echo ""
echo "  Frontend: http://localhost:3000"
echo "  Backend:  http://localhost:8000"
echo "  API Docs: http://localhost:8000/docs"
echo ""
echo "  Press Ctrl+C to stop"
echo ""

# Wait for either process
wait
