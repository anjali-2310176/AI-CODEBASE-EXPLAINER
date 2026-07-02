#!/usr/bin/env bash
# One-command startup for local demo
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "Creating .env from .env.example..."
  cp .env.example .env
  echo ""
  echo "⚠️  Add your OPENAI_API_KEY to .env before using RAG chat!"
  echo ""
fi

if ! grep -q "OPENAI_API_KEY=sk-" .env 2>/dev/null; then
  echo "Reminder: set OPENAI_API_KEY in .env for embeddings + chat"
fi

echo "Starting services with Docker Compose..."
docker compose up --build -d

echo ""
echo "✅ AI Codebase Explainer is starting"
echo ""
echo "   Frontend:  http://localhost:3000"
echo "   API docs:  http://localhost:8000/docs"
echo "   Health:    http://localhost:8000/health"
echo ""
echo "Wait ~30s for Neo4j + Postgres, then open the frontend."
echo "Try analyzing: https://github.com/tiangolo/fastapi"
echo ""
echo "Logs: docker compose logs -f backend"
