#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env (defaults to the offline SQLite demo)"
fi

echo "Starting Docker Compose..."
docker compose up --build -d

echo ""
echo "✅ AI Codebase Explainer"
echo "   Frontend:  http://localhost:3000"
echo "   API:       http://localhost:8000/docs"
echo "   Health:    http://localhost:8000/health"
echo ""
echo "This Docker path is optional; the main demo runs locally with SQLite."
echo "Logs: docker compose logs -f backend"
