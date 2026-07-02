# AI Codebase Explainer

**A full-stack RAG application that explains any public Python GitHub repository.**

Paste a repo URL → the system clones it, parses the code, builds a knowledge graph, indexes embeddings, and answers your questions using **Retrieval-Augmented Generation**.

> Portfolio project demonstrating software engineering + RAG/LLM skills.

---

## What this showcases

| Skill | How it's demonstrated |
|-------|----------------------|
| **RAG** | Code chunked → embedded → FAISS retrieval → context injected into LLM prompt |
| **LLM orchestration** | LangGraph agent with retrieve → generate pipeline |
| **Backend engineering** | FastAPI, async jobs, PostgreSQL, structured API |
| **Data engineering** | Tree-sitter AST parsing, Neo4j knowledge graph |
| **Frontend** | React UI with live job progress + retrieved source display |
| **DevOps** | Docker Compose multi-service stack |

---

## Demo flow (2 minutes)

1. **Start the app**
   ```bash
   chmod +x scripts/start.sh
   ./scripts/start.sh
   ```
   Or manually: `cp .env.example .env` → add `OPENAI_API_KEY` → `docker compose up --build`

2. **Open** http://localhost:3000

3. **Analyze** a repo (start small):
   ```
   https://github.com/tiangolo/fastapi
   ```

4. **Wait** for status = `completed` (progress bar shows pipeline stages)

5. **Go to "RAG Chat"** tab → ask:
   - *"What is the main entry point?"*
   - *"How is routing handled?"*

6. **See retrieved sources** below the answer — that's the RAG retrieval step visible in the UI.

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────────────────────┐
│  React UI   │────▶│   FastAPI    │────▶│  Ingestion Pipeline             │
│  (Vite)     │     │   REST API   │     │  Clone → Parse → Graph → Index  │
└─────────────┘     └──────────────┘     └─────────────────────────────────┘
                            │                          │            │
                            ▼                          ▼            ▼
                    ┌──────────────┐           ┌──────────┐  ┌──────────┐
                    │  LangGraph   │           │  Neo4j   │  │  FAISS   │
                    │  RAG Agent   │◀──────────│  Graph   │  │  Vectors │
                    └──────────────┘           └──────────┘  └──────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │   OpenAI     │
                    │  embed+chat  │
                    └──────────────┘
```

### RAG pipeline (the core)

1. **Retrieve** — User question is embedded; FAISS returns top-k similar code chunks
2. **Augment** — Retrieved chunks are wrapped as untrusted context in the prompt
3. **Generate** — GPT-4o-mini answers using only that context (never the full repo)

---

## Tech stack

- **Backend:** FastAPI, SQLAlchemy, LangGraph, Tree-sitter, OpenAI
- **Databases:** PostgreSQL (metadata), Neo4j (knowledge graph), FAISS (vectors)
- **Frontend:** React, TypeScript, Vite
- **Infra:** Docker Compose

---

## Prerequisites

- Docker & Docker Compose
- OpenAI API key ([platform.openai.com](https://platform.openai.com))
- ~2 GB free disk space

---

## Local development

**Full stack (Docker):**
```bash
docker compose up --build
```

**Backend only:**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Start Postgres + Neo4j separately, or use docker compose up postgres neo4j -d
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
| `POST /api/v1/chat` | **RAG Q&A** — returns answer + retrieved sources |
| `POST /api/v1/readme` | Generate README from analysis |
| `POST /api/v1/diagram` | Generate Mermaid architecture diagram |

Full docs at http://localhost:8000/docs

---

## Project structure

```
backend/app/
├── api/routes.py       # REST endpoints
├── services/
│   ├── pipeline.py     # Clone → parse → graph → embed
│   ├── embeddings.py   # FAISS vector index (RAG retrieval)
│   ├── agent.py        # LangGraph RAG agent
│   ├── graph.py        # Neo4j knowledge graph
│   └── parser/         # Tree-sitter code parser
├── security/           # Input validation, prompt injection guards
└── main.py

frontend/src/
├── App.tsx             # Main UI (analyze + RAG chat + about)
└── api.ts              # API client
```

---

## Tips for your portfolio

- **Record a 60s demo** showing ingest → question → retrieved sources
- **Highlight the RAG tab** — recruiters want to see retrieval, not just chat
- **Mention tradeoffs** in interviews: FAISS over Pinecone (local/demo), LangGraph over raw prompts (structured pipeline)
- **Suggested repos to demo:** `tiangolo/fastapi`, `encode/httpx`, `pallets/click`

---

## License

MIT — free to use for portfolio and learning.
