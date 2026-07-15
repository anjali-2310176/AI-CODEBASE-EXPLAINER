# AI Codebase Explainer

**A lightweight code exploration app for public Python GitHub repositories.**

Paste a repo URL → the system clones it, parses the code, stores searchable chunks in SQLite, and answers questions from retrieved code.

> Portfolio project demonstrating software engineering and retrieval skills.

---

## What this showcases

| Skill | How it's demonstrated |
|-------|----------------------|
| **Backend engineering** | FastAPI, async jobs, structured API |
| **Data handling** | Tree-sitter AST parsing, SQLite chunk storage |
| **Frontend** | React UI with live job progress + retrieved source display |
| **DevOps** | One-command local launch |

---

## Prerequisites

- Python 3.12+ for local dev
- Docker optional if you want to package the app later

This demo runs fully offline by default.

---

## Optional AI later

If you want AI-generated summaries later, you can wire in a provider such as Groq or Ollama. The default demo does not require any API key.

---

## Demo flow (2 minutes)

1. **Start the app**
   ```bash
   chmod +x scripts/run-local.sh
   ./scripts/run-local.sh
   ```

2. **Open** http://localhost:5173

3. **Analyze** a repo (start small):
   ```
   https://github.com/tiangolo/fastapi
   ```

4. **Wait** for status = `completed` (progress bar shows pipeline stages)

5. **Go to "Code Search"** tab → ask:
   - *"What is the main entry point?"*
   - *"How is routing handled?"*

6. **See retrieved sources** below the answer — that is the retrieval step visible in the UI.

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────────────────────┐
│  React UI   │────▶│   FastAPI    │────▶│  Ingestion Pipeline             │
│  (Vite)     │     │   REST API   │     │  Clone → Parse → Store chunks   │
└─────────────┘     └──────────────┘     └─────────────────────────────────┘
                            │                          │            │
                            ▼                          ▼            ▼
          ┌──────────────┐           ┌──────────┐
          │ In-memory    │           │ SQLite   │
          │ graph map    │◀──────────│ chunks   │
          └──────────────┘           └──────────┘
```

### Retrieval pipeline (the core)

1. **Parse** — Tree-sitter extracts classes, functions, and imports from Python files
2. **Store** — Clean code chunks are saved in SQLite alongside repository metadata
3. **Retrieve** — Keyword matching returns the most relevant chunks for a question
4. **Answer** — The app responds directly from the retrieved code so it works offline

---

## Tech stack

- **LLM:** Optional later; offline by default
- **Databases:** SQLite for metadata and code chunks
- **Frontend:** React, TypeScript, Vite
- **Infra:** One-command local launcher

---

## Local development

**Backend only:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Frontend only:**
```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

---

## API highlights

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/ingest` | Start repo analysis |
| `GET /api/v1/jobs/{id}` | Poll progress |
| `POST /api/v1/chat` | Retrieval Q&A — returns answer + retrieved sources |
| `POST /api/v1/readme` | Generate a plain-text repository summary |
| `POST /api/v1/diagram` | Generate a Mermaid-style structure diagram |

Full docs at http://localhost:8000/docs

---

## Project structure

```
backend/app/
├── api/routes.py       # REST endpoints
├── services/
│   ├── pipeline.py     # Clone → parse → store chunks
│   ├── embeddings.py   # SQLite chunk store and retrieval
│   ├── agent.py        # Offline retrieval + answer formatting
│   ├── graph.py        # In-memory code map
│   └── parser/         # Tree-sitter code parser
├── security/           # Input validation, prompt injection guards
└── main.py

frontend/src/
├── App.tsx             # Main UI (analyze + code search + about)
└── api.ts              # API client
```

---

## Tips for your portfolio

- **Record a 60s demo** showing ingest → question → retrieved sources
- **Highlight the Code Search tab** — recruiters want to see retrieval, not just chat
- **Mention tradeoffs** in interviews: SQLite chunk store over heavier vector infrastructure for a simple portfolio demo
- **Suggested repos to demo:** `tiangolo/fastapi`, `encode/httpx`, `pallets/click`

---

## License

MIT — free to use for portfolio and learning.
