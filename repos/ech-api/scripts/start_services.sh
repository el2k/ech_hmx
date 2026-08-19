#!/bin/bash

# Start both main API and internal services
# This script is for local development

set -e

echo "=========================================="
echo "Starting TGO-Tech API Services"
echo "=========================================="
echo ""
echo "Main API:      http://localhost:8000"
echo "Internal API:  http://localhost:8001"
echo ""
echo "Press Ctrl+C to stop all services"
echo "=========================================="
echo ""

# Trap Ctrl+C and kill all background processes
trap 'echo ""; echo "Stopping services..."; kill $(jobs -p); exit' INT TERM

# Start main API in background
echo "Starting Main API on port 8000..."
poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
MAIN_PID=$!

# Wait a bit for main API to start
sleep 2

# Start internal service in background
echo "Starting Internal Service on port 8001..."
poetry run uvicorn app.internal:internal_app --host 127.0.0.1 --port 8001 --reload &
INTERNAL_PID=$!

echo ""
echo "✅ Both services started successfully!"
echo ""
echo "Main API PID:      $MAIN_PID"
echo "Internal API PID:  $INTERNAL_PID"
echo ""
echo "📚 API Documentation:"
echo "   Main API:      http://localhost:8000/v1/docs"
echo "   Internal API:  http://localhost:8001/internal/docs"
echo ""
echo "🏥 Health Checks:"
echo "   Main API:      http://localhost:8000/health"
echo "   Internal API:  http://localhost:8001/health"
echo ""

# Wait for all background processes
wait

