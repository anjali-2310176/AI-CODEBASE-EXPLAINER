import { useCallback, useEffect, useState } from "react";
import {
  askQuestion,
  generateDiagram,
  generateReadme,
  getJob,
  ingestRepo,
  listRepos,
  ChatSource,
  Job,
  Repository,
} from "./api";

const SAMPLE_QUESTIONS = [
  "What is the main entry point of this project?",
  "How is routing handled?",
  "What are the core classes and their responsibilities?",
  "Explain the project architecture in simple terms.",
];

const PIPELINE_STEPS = [
  { key: "cloning", label: "Clone repo" },
  { key: "parsing", label: "Parse AST" },
  { key: "graphing", label: "Build graph" },
  { key: "indexing", label: "Embed + index" },
  { key: "completed", label: "Ready" },
];

type Tab = "analyze" | "chat" | "about";

export default function App() {
  const [tab, setTab] = useState<Tab>("analyze");
  const [url, setUrl] = useState("https://github.com/tiangolo/fastapi");
  const [repos, setRepos] = useState<Repository[]>([]);
  const [selected, setSelected] = useState<Repository | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<ChatSource[]>([]);
  const [readme, setReadme] = useState("");
  const [diagram, setDiagram] = useState("");
  const [loading, setLoading] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const data = await listRepos();
      setRepos(data.items);
      if (selected) {
        const updated = data.items.find((r) => r.id === selected.id);
        if (updated) setSelected(updated);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [selected]);

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (!job || job.status === "completed" || job.status === "failed") return;
    const poll = setInterval(async () => {
      try {
        const status = await getJob(job.id);
        setJob(status);
        if (status.status === "completed" || status.status === "failed") {
          setLoading(false);
          refresh();
          if (status.status === "completed") setTab("chat");
        }
      } catch {
        clearInterval(poll);
        setLoading(false);
      }
    }, 2000);
    return () => clearInterval(poll);
  }, [job, refresh]);

  async function handleIngest() {
    setLoading(true);
    setError("");
    setJob(null);
    try {
      const newJob = await ingestRepo(url);
      setJob(newJob);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setLoading(false);
    }
  }

  async function handleAsk(q?: string) {
    const text = q ?? question;
    if (!selected || !text.trim()) return;
    setLoading(true);
    setError("");
    setAnswer("");
    setSources([]);
    try {
      const res = await askQuestion(selected.id, text);
      setAnswer(res.answer);
      setSources(res.sources);
      setQuestion(text);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleReadme() {
    if (!selected) return;
    setLoading(true);
    try {
      setReadme(await generateReadme(selected.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleDiagram() {
    if (!selected) return;
    setLoading(true);
    try {
      setDiagram(await generateDiagram(selected.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const readyRepos = repos.filter((r) => r.status === "completed");

  return (
    <div className="app">
      <header className="hero">
        <div className="hero-text">
          <span className="eyebrow">Portfolio Project · RAG + Full-Stack</span>
          <h1>AI Codebase Explainer</h1>
          <p>
            Paste any public Python GitHub repo. The system clones it, parses the code,
            builds a knowledge graph, indexes embeddings in FAISS, and answers your
            questions using retrieval-augmented generation.
          </p>
        </div>
        <div className="tech-pills">
          {["FastAPI", "React", "LangGraph", "FAISS", "Neo4j", "Tree-sitter"].map((t) => (
            <span key={t} className="pill">{t}</span>
          ))}
        </div>
      </header>

      <nav className="tabs">
        {(["analyze", "chat", "about"] as Tab[]).map((t) => (
          <button
            key={t}
            className={tab === t ? "active" : ""}
            onClick={() => setTab(t)}
          >
            {t === "analyze" ? "1. Analyze" : t === "chat" ? "2. RAG Chat" : "How it works"}
          </button>
        ))}
      </nav>

      {error && <div className="error">{error}</div>}

      {tab === "analyze" && (
        <>
          <section className="card">
            <h2>Analyze a GitHub Repository</h2>
            <p className="hint">Try a small repo first, e.g. <code>tiangolo/fastapi</code></p>
            <div className="row">
              <input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://github.com/owner/repo"
              />
              <button onClick={handleIngest} disabled={loading}>
                {loading ? "Analyzing…" : "Start analysis"}
              </button>
            </div>

            {job && (
              <div className="progress-section">
                <div className="progress-bar">
                  <div className="progress-fill" style={{ width: `${job.progress}%` }} />
                </div>
                <div className="pipeline-steps">
                  {PIPELINE_STEPS.map((step) => (
                    <span
                      key={step.key}
                      className={`step ${
                        job.status === step.key || (job.progress >= 100 && step.key === "completed")
                          ? "active"
                          : ""
                      } ${job.stage === step.key ? "current" : ""}`}
                    >
                      {step.label}
                    </span>
                  ))}
                </div>
                <small>Status: {job.status} · {job.progress}% · stage: {job.stage}</small>
              </div>
            )}
          </section>

          <section className="card">
            <h2>Analyzed Repositories</h2>
            {repos.length === 0 ? (
              <p className="empty">No repositories yet. Analyze one above to get started.</p>
            ) : (
              <ul className="repo-list">
                {repos.map((r) => (
                  <li
                    key={r.id}
                    className={selected?.id === r.id ? "selected" : ""}
                    onClick={() => setSelected(r)}
                  >
                    <div className="repo-row">
                      <strong>{r.name}</strong>
                      <span className={`badge ${r.status}`}>{r.status}</span>
                    </div>
                    <small>{r.file_count} files · {r.entity_count} code entities</small>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}

      {tab === "chat" && (
        <>
          {readyRepos.length === 0 ? (
            <section className="card empty-state">
              <h2>No repo ready yet</h2>
              <p>Go to <button className="link" onClick={() => setTab("analyze")}>Analyze</button> and wait for status = completed.</p>
            </section>
          ) : (
            <>
              <section className="card">
                <h2>Select repository</h2>
                <div className="repo-chips">
                  {readyRepos.map((r) => (
                    <button
                      key={r.id}
                      className={`chip ${selected?.id === r.id ? "selected" : ""}`}
                      onClick={() => { setSelected(r); setAnswer(""); setSources([]); }}
                    >
                      {r.name}
                    </button>
                  ))}
                </div>
              </section>

              {selected && (
                <>
                  <section className="card rag-card">
                    <h2>RAG Chat — {selected.name}</h2>
                    <p className="hint">
                      Your question is embedded → top-k similar code chunks retrieved from FAISS → LLM answers using only that context.
                    </p>

                    <div className="sample-questions">
                      {SAMPLE_QUESTIONS.map((q) => (
                        <button key={q} className="chip" onClick={() => handleAsk(q)} disabled={loading}>
                          {q}
                        </button>
                      ))}
                    </div>

                    <div className="row">
                      <input
                        value={question}
                        onChange={(e) => setQuestion(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && handleAsk()}
                        placeholder="Ask anything about this codebase…"
                      />
                      <button onClick={() => handleAsk()} disabled={loading || !question.trim()}>
                        {loading ? "Retrieving…" : "Ask"}
                      </button>
                    </div>

                    {answer && (
                      <div className="answer-block">
                        <h3>Answer</h3>
                        <pre>{answer}</pre>
                      </div>
                    )}

                    {sources.length > 0 && (
                      <div className="sources-block">
                        <h3>Retrieved context (RAG sources)</h3>
                        <p className="hint">These code chunks were retrieved by vector similarity — this is the &quot;R&quot; in RAG.</p>
                        {sources.map((s, i) => (
                          <div key={i} className="source-card">
                            <div className="source-header">
                              <span className="source-name">{s.name}</span>
                              <span className="source-type">{s.type}</span>
                              <span className="source-score">score: {s.score.toFixed(3)}</span>
                            </div>
                            <div className="source-path">{s.file_path}</div>
                            <pre className="source-snippet">{s.content?.slice(0, 400)}…</pre>
                          </div>
                        ))}
                      </div>
                    )}
                  </section>

                  <section className="card row actions">
                    <button onClick={handleReadme} disabled={loading}>Generate README</button>
                    <button onClick={handleDiagram} disabled={loading}>Generate diagram</button>
                  </section>

                  {readme && (
                    <section className="card">
                      <h2>Generated README</h2>
                      <pre>{readme}</pre>
                    </section>
                  )}

                  {diagram && (
                    <section className="card">
                      <h2>Architecture diagram (Mermaid)</h2>
                      <pre>{diagram}</pre>
                    </section>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}

      {tab === "about" && (
        <section className="card about">
          <h2>How this project works (RAG pipeline)</h2>
          <div className="flow">
            <div className="flow-step">
              <span className="flow-num">1</span>
              <div>
                <strong>Clone &amp; parse</strong>
                <p>Shallow-clone the GitHub repo. Tree-sitter parses Python files into classes, functions, and imports.</p>
              </div>
            </div>
            <div className="flow-arrow">↓</div>
            <div className="flow-step">
              <span className="flow-num">2</span>
              <div>
                <strong>Knowledge graph</strong>
                <p>Entities and relationships (imports, contains, defines) stored in Neo4j for structural queries.</p>
              </div>
            </div>
            <div className="flow-arrow">↓</div>
            <div className="flow-step">
              <span className="flow-num">3</span>
              <div>
                <strong>Embed &amp; index</strong>
                <p>Code chunks embedded with OpenAI <code>text-embedding-3-small</code>, stored in a FAISS vector index on disk.</p>
              </div>
            </div>
            <div className="flow-arrow">↓</div>
            <div className="flow-step highlight">
              <span className="flow-num">4</span>
              <div>
                <strong>RAG Q&amp;A (LangGraph)</strong>
                <p>
                  <b>Retrieve:</b> embed the user question → search FAISS for top-k similar chunks.<br />
                  <b>Augment:</b> inject retrieved code into the prompt as context.<br />
                  <b>Generate:</b> GPT answers using only that context — never the full repo.
                </p>
              </div>
            </div>
          </div>

          <h3>Skills demonstrated</h3>
          <ul className="skills">
            <li>End-to-end system design (frontend → API → workers → databases)</li>
            <li>RAG: chunking, embedding, vector search, context injection</li>
            <li>LLM orchestration with LangGraph</li>
            <li>AST parsing with Tree-sitter</li>
            <li>Graph data modeling (Neo4j)</li>
            <li>Async Python (FastAPI), React UI, Docker Compose</li>
          </ul>
        </section>
      )}

      <footer>
        <p>Built as a portfolio project · AI Codebase Explainer</p>
      </footer>
    </div>
  );
}
