import { useCallback, useEffect, useState } from "react";
import {
  askQuestion,
  checkHealth,
  generateDiagram,
  generateReadme,
  getJob,
  ingestRepo,
  listRepos,
  ChatSource,
  HealthInfo,
  Job,
  Repository,
} from "./api";

const SAMPLE_QUESTIONS = [
  "What is the main entry point?",
  "How is routing handled?",
  "What are the core classes?",
  "Explain the architecture.",
];

const PIPELINE_STEPS = [
  { key: "cloning", label: "Clone" },
  { key: "parsing", label: "Parse" },
  { key: "graphing", label: "Map" },
  { key: "indexing", label: "Store" },
  { key: "completed", label: "Ready" },
];

type Tab = "analyze" | "chat" | "about";

const NAV: { id: Tab; label: string; icon: string }[] = [
  { id: "analyze", label: "Analyze Repo", icon: "◈" },
  { id: "chat", label: "Code Search", icon: "◉" },
  { id: "about", label: "How It Works", icon: "◎" },
];

function ArchitectureAnimation() {
  return (
    <div className="arch-diagram">
      <div className="arch-row">
        <div className="arch-node">
          <div className="node-icon">📦</div>
          <div className="node-title">GitHub Repo</div>
          <div className="node-desc">Source Code</div>
        </div>
        
        <div className="arch-line">
          <div className="arch-packet"></div>
          <div className="arch-packet packet-delay-1"></div>
        </div>

        <div className="arch-node">
          <div className="node-icon">🌳</div>
          <div className="node-title">Tree-sitter</div>
          <div className="node-desc">AST Parsing</div>
          <div className="arch-v-line">
            <div className="arch-v-packet"></div>
          </div>
        </div>

        <div className="arch-line">
          <div className="arch-packet packet-delay-1"></div>
          <div className="arch-packet packet-delay-2"></div>
        </div>

        <div className="arch-node">
          <div className="node-icon">🧠</div>
          <div className="node-title">Embeddings</div>
          <div className="node-desc">MiniLM-L6-v2</div>
        </div>
      </div>

      <div className="arch-row" style={{ marginTop: "40px" }}>
        <div className="arch-node">
          <div className="node-icon">🗄️</div>
          <div className="node-title">SQLite Vector Store</div>
          <div className="node-desc">Persistent Chunks</div>
        </div>

        <div className="arch-line">
          <div className="arch-packet" style={{ animationDirection: "reverse" }}></div>
          <div className="arch-packet packet-delay-1" style={{ animationDirection: "reverse" }}></div>
        </div>

        <div className="arch-node">
          <div className="node-icon">✨</div>
          <div className="node-title">Gemini RAG</div>
          <div className="node-desc">Contextual Answers</div>
        </div>
      </div>
    </div>
  );
}

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
  const [health, setHealth] = useState<HealthInfo | null>(null);

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
    checkHealth().then(setHealth);
    const interval = setInterval(() => checkHealth().then(setHealth), 15000);
    return () => clearInterval(interval);
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
      setJob(await ingestRepo(url));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setLoading(false);
    }
  }

  async function handleAsk(qOverride?: string) {
    if (!selected) return;
    const q = qOverride || question;
    if (!q.trim()) return;
    setQuestion(q);
    setLoading(true);
    setAnswer("");
    setSources([]);
    setError("");
    try {
      const res = await askQuestion(selected.id, q);
      setAnswer(res.answer);
      setSources(res.sources);
    } catch (err: any) {
      setAnswer(`**Error generating answer:**\n${err.message || String(err)}\n\nPlease wait a moment and try again if this is a rate limit.`);
    } finally {
      setLoading(false);
    }
  }

  const readyRepos = repos.filter((r) => r.status === "completed");
  const isOnline = health?.status === "ok";
  const isOfflineMode = health?.llm?.llm_provider === "offline";

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <div className="brand-mark">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
              </svg>
            </div>
            <div>
              <div className="brand-title">Lens</div>
              <div className="brand-sub">Semantic Code Search</div>
            </div>
          </div>
          <div className={`status-pill ${isOnline ? "online" : "offline"}`}>
            <span className="status-dot" />
            {isOnline ? "API connected" : "API offline — run ./scripts/run-local.sh"}
          </div>
        </div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <div className="nav-label">Navigation</div>
          <nav className="nav">
            {NAV.map((n) => (
              <button
                key={n.id}
                className={`nav-btn ${tab === n.id ? "active" : ""}`}
                onClick={() => setTab(n.id)}
              >
                <span className="nav-icon">{n.icon}</span>
                {n.label}
              </button>
            ))}
          </nav>
        </aside>

        <main className="main">
          {error && (
            <div className="alert alert-error">
              <span>⚠</span>
              <span>{error}</span>
            </div>
          )}

          {!isOnline && (
            <div className="alert alert-warn">
              <span>◎</span>
              <span>
                Backend not running. Open a terminal and run:{" "}
                <code>./scripts/run-local.sh</code> then visit{" "}
                <code>http://localhost:5173</code>
              </span>
            </div>
          )}

          {tab === "analyze" && (
            <>
              <div className="hero">
                <div className="hero-content">
                  <div className="hero-illustration fade-up-1">
                    <svg width="120" height="120" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <circle cx="50" cy="50" r="40" stroke="url(#paint0_linear)" strokeWidth="2" strokeDasharray="4 4" className="spin-slow" />
                      <circle cx="50" cy="50" r="28" fill="url(#paint1_linear)" fillOpacity="0.1" stroke="url(#paint2_linear)" strokeWidth="1.5" />
                      <path d="M42 42L58 58M58 42L42 58" stroke="url(#paint3_linear)" strokeWidth="2" strokeLinecap="round" className="pulse-fast" />
                      <circle cx="50" cy="50" r="8" fill="url(#paint4_linear)" />
                      <defs>
                        <linearGradient id="paint0_linear" x1="10" y1="50" x2="90" y2="50" gradientUnits="userSpaceOnUse">
                          <stop stopColor="#4F46E5" />
                          <stop offset="1" stopColor="#10B981" stopOpacity="0" />
                        </linearGradient>
                        <linearGradient id="paint1_linear" x1="22" y1="22" x2="78" y2="78" gradientUnits="userSpaceOnUse">
                          <stop stopColor="#4338CA" />
                          <stop offset="1" stopColor="#10B981" />
                        </linearGradient>
                        <linearGradient id="paint2_linear" x1="22" y1="22" x2="78" y2="78" gradientUnits="userSpaceOnUse">
                          <stop stopColor="#4F46E5" />
                          <stop offset="1" stopColor="#34D399" />
                        </linearGradient>
                        <linearGradient id="paint3_linear" x1="42" y1="42" x2="58" y2="58" gradientUnits="userSpaceOnUse">
                          <stop stopColor="#818CF8" />
                          <stop offset="1" stopColor="#A7F3D0" />
                        </linearGradient>
                        <linearGradient id="paint4_linear" x1="42" y1="42" x2="58" y2="58" gradientUnits="userSpaceOnUse">
                          <stop stopColor="#4F46E5" />
                          <stop offset="1" stopColor="#10B981" />
                        </linearGradient>
                      </defs>
                    </svg>
                  </div>
                  <h1 className="fade-up-2">AI-Powered Codebase Explainer</h1>
                  <p className="fade-up-3">Instantly search, map, and understand any public Python repository using semantic vector embeddings and Gemini RAG.</p>
                  <div className="workflow-seq fade-up-4">
                    <span className="wf-step">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/></svg>
                      Repository
                    </span>
                    <span className="wf-arrow">→</span>
                    <span className="wf-step">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                      Analysis
                    </span>
                    <span className="wf-arrow">→</span>
                    <span className="wf-step">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
                      Insights
                    </span>
                    <span className="wf-arrow">→</span>
                    <span className="wf-step">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                      Output
                    </span>
                  </div>
                </div>
              </div>

              <section className="card">
                <div className="card-header">
                  <h2>New analysis</h2>
                </div>
                <p className="hint">
                  Start with a small repo — e.g. <code>encode/httpx</code>
                </p>
                <div className="input-row">
                  <input
                    className="input"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://github.com/owner/repo"
                  />
                  <button className="btn btn-primary" onClick={handleIngest} disabled={loading || !isOnline}>
                    {loading ? (
                      <>
                        <svg className="animate-spin" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
                        Analyzing…
                      </>
                    ) : (
                      <>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                        Start analysis
                      </>
                    )}
                  </button>
                </div>

                {job && (
                  <div className="progress-wrap">
                    <div className="progress-track">
                      <div className="progress-bar" style={{ width: `${job.progress}%` }} />
                    </div>
                    <div className="pipeline">
                      {PIPELINE_STEPS.map((step) => (
                        <span
                          key={step.key}
                          className={`step-tag ${
                            job.status === step.key || (job.progress >= 100 && step.key === "completed")
                              ? "done"
                              : ""
                          } ${job.stage === step.key || job.status === step.key ? "current" : ""}`}
                        >
                          {step.label}
                        </span>
                      ))}
                    </div>
                    <div className="progress-meta">
                      {job.status} · {job.progress}% · {job.stage}
                    </div>
                  </div>
                )}
              </section>

              <section className="card">
                <div className="card-header">
                  <h2>Repositories</h2>
                  <span className="badge completed">{repos.length} total</span>
                </div>
                {repos.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-icon">📂</div>
                    <h2>No repositories yet</h2>
                    <p>Analyze a GitHub repo above to get started.</p>
                  </div>
                ) : (
                  <div className="repo-grid">
                    {repos.map((r) => (
                      <div
                        key={r.id}
                        className={`repo-item ${selected?.id === r.id ? "selected" : ""}`}
                        onClick={() => setSelected(r)}
                      >
                        <div>
                          <div className="repo-name">{r.name}</div>
                          <div className="repo-meta">
                            {r.file_count} files · {r.entity_count} entities
                          </div>
                        </div>
                        <span className={`badge ${r.status}`}>{r.status}</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}

          {tab === "chat" && (
            <>
              <div className="page-header">
                <h1>Code Search</h1>
                <p>
                  Ask questions about the indexed code. Semantic vector search retrieves relevant
                  chunks; Gemini generates a grounded answer.
                </p>
              </div>

              {readyRepos.length === 0 ? (
                <section className="card empty-state">
                  <div className="empty-icon">💬</div>
                  <h2>No repo ready</h2>
                  <p>
                    Analyze a repository first, then return here when status is{" "}
                    <code>completed</code>.
                  </p>
                  <button className="btn btn-primary" style={{ marginTop: "1rem" }} onClick={() => setTab("analyze")}>
                    Go to Analyze
                  </button>
                </section>
              ) : (
                <>
                  <section className="card">
                    <h2>Select repository</h2>
                    <div className="chip-row">
                      {readyRepos.map((r) => (
                        <button
                          key={r.id}
                          className={`chip ${selected?.id === r.id ? "selected" : ""}`}
                          onClick={() => {
                            setSelected(r);
                            setAnswer("");
                            setSources([]);
                          }}
                        >
                          {r.name}
                        </button>
                      ))}
                    </div>
                  </section>

                  {selected && (
                    <>
                      <section className="card search-panel">
                        <h2>{selected.name}</h2>
                        <p className="hint">
                          Search question → retrieve chunks → answer from code context
                        </p>

                        <div className="chip-row">
                          {SAMPLE_QUESTIONS.map((q) => (
                            <button key={q} className="chip" onClick={() => handleAsk(q)} disabled={loading}>
                              {q}
                            </button>
                          ))}
                        </div>

                        <div className="input-row">
                          <input
                            className="input"
                            value={question}
                            onChange={(e) => setQuestion(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && handleAsk()}
                            placeholder="Ask anything about this codebase…"
                          />
                          <button
                            className="btn btn-primary"
                            onClick={() => handleAsk()}
                            disabled={loading || !question.trim()}
                          >
                            {loading ? (
                              <>
                                <svg className="animate-spin" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
                                Asking Gemini…
                              </>
                            ) : (
                              <>
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                                Ask
                              </>
                            )}
                          </button>
                        </div>

                        {loading && !answer && (
                          <div className="answer-box">
                            <h3>Answer</h3>
                            <div className="skeleton-box" style={{ height: "120px", marginTop: "0.5rem" }} />
                          </div>
                        )}

                        {!loading && answer && (
                          <div className="answer-box">
                            <h3>Answer</h3>
                            <div className="code-block" style={{ marginTop: "0.5rem" }}>
                              {/* Using simple markdown-style rendering for demo purposes */}
                              {answer.split('\n').map((line, i) => {
                                if (line.startsWith('**')) return <strong key={i}>{line.replace(/\*\*/g, '')}<br/></strong>;
                                if (line.startsWith('```')) return <br key={i}/>;
                                return <span key={i}>{line}<br/></span>;
                              })}
                            </div>
                          </div>
                        )}

                        {sources.length > 0 && (
                          <div className="sources">
                            <h3>Retrieved sources</h3>
                            <p className="hint">Code chunks matched by SQLite-backed retrieval.</p>
                            {sources.map((s, i) => (
                              <div key={i} className="source-item">
                                <div className="source-top">
                                  <span className="source-name">{s.name}</span>
                                  <span className="source-type">{s.type}</span>
                                  <span className="source-score">{s.score.toFixed(3)}</span>
                                </div>
                                <div className="source-path">{s.file_path}</div>
                                <div className="source-code">{s.content?.slice(0, 350)}…</div>
                              </div>
                            ))}
                          </div>
                        )}
                      </section>

                      <section className="card">
                        <h2>Quick docs</h2>
                        <div className="action-row">
                          <button className="btn btn-secondary" onClick={async () => {
                            if (!selected) return;
                            setLoading(true);
                            try { setReadme(await generateReadme(selected.id)); }
                            catch (e) { setError(e instanceof Error ? e.message : String(e)); }
                            finally { setLoading(false); }
                          }} disabled={loading}>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                            README
                          </button>
                          <button className="btn btn-secondary" onClick={async () => {
                            if (!selected) return;
                            setLoading(true);
                            try { setDiagram(await generateDiagram(selected.id)); }
                            catch (e) { setError(e instanceof Error ? e.message : String(e)); }
                            finally { setLoading(false); }
                          }} disabled={loading}>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
                            Diagram
                          </button>
                        </div>
                      </section>

                      {readme && (
                        <section className="card">
                          <h2>Repository summary</h2>
                          <pre className="code-block">{readme}</pre>
                        </section>
                      )}

                      {diagram && (
                        <section className="card">
                          <h2>Structure diagram</h2>
                          <pre className="code-block">{diagram}</pre>
                        </section>
                      )}
                    </>
                  )}
                </>
              )}
            </>
          )}

          {tab === "about" && (
            <>
              <div className="page-header">
                <h1>How it works</h1>
                <p>A code exploration tool demonstrating a full RAG pipeline: AST parsing → vector embeddings → semantic retrieval → Gemini-generated answers.</p>
              </div>

              <section className="card">
                <h2>Demo pipeline</h2>
                <div className="flow-list">
                  {[
                    { n: "1", title: "Clone & parse", desc: "Shallow-clone the repo. Tree-sitter extracts classes, functions, and imports from Python files.", featured: false },
                    { n: "2", title: "Map structure", desc: "Entities and relationships are kept in memory for quick exploration and module summaries.", featured: false },
                    { n: "3", title: "Store chunks", desc: "Parsed code chunks are stored in SQLite so retrieval stays simple and portable.", featured: false },
                    { n: "4", title: "Answer questions", desc: "Search: match chunks by keywords. Respond: summarize directly from retrieved code, with optional AI later.", featured: true },
                  ].map((step) => (
                    <div key={step.n} className={`flow-item ${step.featured ? "featured" : ""}`}>
                      <span className="flow-num">{step.n}</span>
                      <div>
                        <strong>{step.title}</strong>
                        <p>{step.desc}</p>
                      </div>
                    </div>
                  ))}
                </div>

                <h3>System Architecture</h3>
                <ArchitectureAnimation />
                <ul className="skills-list">
                  <li>End-to-end RAG pipeline — retrieval-augmented generation with Gemini</li>
                  <li>Semantic vector search with sentence-transformers (all-MiniLM-L6-v2)</li>
                  <li>AST parsing with Tree-sitter — modules, classes, functions, imports</li>
                  <li>FastAPI async backend with SQLite chunk store</li>
                  <li>In-memory code graph for structure exploration</li>
                  <li>Offline-first design with graceful LLM fallback</li>
                </ul>
              </section>
            </>
          )}
        </main>
      </div>

      <footer className="footer">
        Built with FastAPI · React · Sentence-Transformers · Gemini · <span>Lens</span>
      </footer>
    </div>
  );
}
