#!/bin/bash

cleanup() {
  echo ""
  echo "🛑 Shutting down..."
  docker compose down
  echo "✅ All services stopped."
  exit 0
}

trap cleanup SIGINT SIGTERM EXIT

echo "🚀 Starting DRM Demo (Backend + Frontend)"
echo "==========================================="

# Check Docker is running
if ! docker info > /dev/null 2>&1; then
  echo "❌ Docker is not running. Please start Docker Desktop first."
  exit 1
fi

# Start backend (Postgres + Redis + FastAPI)
echo ""
echo "📦 Starting backend containers..."
docker compose up --build -d

# Wait for backend to be healthy
echo "⏳ Waiting for backend..."
for i in {1..30}; do
  if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "✅ Backend ready at http://localhost:8000"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "❌ Backend failed to start. Check logs: docker compose logs backend"
    exit 1
  fi
  sleep 1
done

# Install frontend deps if needed
if [ ! -d "node_modules" ]; then
  echo ""
  echo "📦 Installing frontend dependencies..."
  npm install
fi

# Start frontend
echo ""
echo "🌐 Starting frontend..."
echo "✅ Frontend will be at http://localhost:3000"
echo ""
echo "Login: viewer@example.com / demo123"
echo "==========================================="
echo ""

npm run dev
