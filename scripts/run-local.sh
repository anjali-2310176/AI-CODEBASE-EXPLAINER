#!/usr/bin/env bash
# Run WITHOUT Docker — fixes "connection refused" when Docker Desktop is off
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== AI Codebase Explainer — Local Mode (no Docker) ==="

# Load .env file first (picks up GEMINI_API_KEY etc.)
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Lite mode overrides (these take priority over .env)
export LITE_MODE=true
export DATABASE_URL=sqlite+aiosqlite:///./data/app.db
export GRAPH_BACKEND=memory
export LLM_PROVIDER=gemini
export REPOS_DIR=./data/repos
export METADATA_DIR=./data/metadata
export CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
export VITE_API_URL=http://127.0.0.1:8000

mkdir -p data/repos data/metadata

# Backend venv
if [ ! -d backend/.venv ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv backend/.venv
fi

source backend/.venv/bin/activate
pip install -q -r backend/requirements.txt

# Frontend deps
if [ ! -d frontend/node_modules ]; then
  echo "Installing frontend dependencies..."
  (cd frontend && npm install)
fi

# Kill stale processes on our ports
for PORT in 8000 5173; do
  lsof -ti :$PORT | xargs kill -9 2>/dev/null || true
done

echo "Starting backend on http://127.0.0.1:8000 ..."
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
cd ..

sleep 10
if ! curl -sf http://127.0.0.1:8000/health >/dev/null; then
  echo "Backend failed to start. Check errors above."
  kill $BACKEND_PID 2>/dev/null || true
  exit 1
fi

echo "Starting frontend on http://127.0.0.1:5173 ..."
(cd frontend && npm run dev -- --host 127.0.0.1) &
FRONTEND_PID=$!

sleep 3
echo ""
echo "============================================"
echo "  App running (no Docker required)"
echo "  Open: http://localhost:5173"
echo "  API:  http://localhost:8000/docs"
echo "============================================"
echo ""
if [ -n "$GEMINI_API_KEY" ]; then
  echo "Mode: Gemini RAG (real AI answers)"
else
  echo "Mode: offline code retrieval (set GEMINI_API_KEY in .env for AI answers)"
fi
echo ""
echo "Press Ctrl+C to stop"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
