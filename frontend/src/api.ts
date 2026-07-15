const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export interface Repository {
  id: string;
  url: string;
  name: string;
  status: string;
  file_count: number;
  entity_count: number;
  error_message?: string;
}

export interface Job {
  id: string;
  repository_id: string;
  status: string;
  stage: string;
  progress: number;
}

export interface ChatSource {
  name: string;
  file_path: string;
  type: string;
  score: number;
  content?: string;
}

export interface HealthInfo {
  status: string;
  version?: string;
  llm?: {
    llm_provider: string;
    embedding_provider: string;
    lite_mode?: boolean;
    cost?: string;
  };
}

export async function checkHealth(): Promise<HealthInfo | null> {
  try {
    const res = await fetch(`${API}/health`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function ingestRepo(url: string): Promise<Job> {
  const res = await fetch(`${API}/api/v1/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getJob(id: string): Promise<Job> {
  const res = await fetch(`${API}/api/v1/jobs/${id}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listRepos(): Promise<{ items: Repository[] }> {
  const res = await fetch(`${API}/api/v1/repositories`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function askQuestion(
  repoId: string,
  question: string
): Promise<{ answer: string; sources: ChatSource[] }> {
  const res = await fetch(`${API}/api/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repository_id: repoId, question }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function generateReadme(repoId: string): Promise<string> {
  const res = await fetch(`${API}/api/v1/readme`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repository_id: repoId }),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.content;
}

export async function generateDiagram(repoId: string): Promise<string> {
  const res = await fetch(`${API}/api/v1/diagram`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repository_id: repoId, diagram_type: "architecture" }),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.mermaid;
}
