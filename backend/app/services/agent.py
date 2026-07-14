import time
from typing import TypedDict

from app.observability.metrics import increment, observe
from app.security.sanitization import sanitize_llm_output, sanitize_user_question
from app.services.embeddings import get_embedding_service
from app.services.graph import get_graph_service
from app.services.llm_provider import generate_answer


class AgentState(TypedDict):
    question: str
    repository_id: str
    context: str
    sources: list[dict]
    answer: str


async def ask_question(repository_id: str, question: str) -> dict:
    """
    Full RAG pipeline:
    1. Sanitize user question
    2. Semantic vector search for relevant code chunks
    3. Build structured context from retrieved sources
    4. Call Gemini to generate a grounded answer
    """
    start = time.perf_counter()

    cleaned_question = sanitize_user_question(question)
    embedder = get_embedding_service()
    sources = await embedder.search(repository_id, cleaned_question)

    # Build context from semantically retrieved chunks
    context_parts = []
    for src in sources:
        header = f"### {src['type']}: `{src['name']}` — {src['file_path']} (line {src.get('line_start', '?')})"
        context_parts.append(f"{header}\n```python\n{src['content']}\n```")

    # Fallback: if no chunks found, use graph entity list
    if not context_parts:
        graph = get_graph_service()
        entities = graph.list_entities(repository_id, limit=15)
        for e in entities:
            context_parts.append(f"- {e['type']}: `{e['name']}` in `{e['file_path']}`")

    context = "\n\n".join(context_parts)
    answer = await generate_answer(context, cleaned_question)

    observe("qa_latency_ms", (time.perf_counter() - start) * 1000)
    increment("questions_answered")
    return {"answer": sanitize_llm_output(answer), "sources": sources}


def generate_readme(repository_id: str) -> str:
    graph = get_graph_service()
    modules = graph.get_module_stats(repository_id)
    entities = graph.list_entities(repository_id, limit=50)
    lines = ["# Repository Overview\n", "## Modules\n"]
    for m in modules[:20]:
        lines.append(f"- `{m['path']}`: {m['classes']} classes, {m['functions']} functions")
    lines.append("\n## Key entities\n")
    for e in entities[:20]:
        lines.append(f"- **{e['type']}** `{e['name']}` in `{e['file_path']}`")
    return "\n".join(lines)


def generate_diagram(repository_id: str, diagram_type: str = "architecture") -> tuple[str, str]:
    graph = get_graph_service()
    subgraph = graph.get_subgraph(repository_id, limit=50)
    nodes = subgraph["nodes"][:15]
    lines = ["graph TD"]
    for n in nodes:
        safe = n["label"].replace(" ", "_").replace("-", "_")[:30]
        lines.append(f'  {safe}["{n["label"]} ({n["type"]})"]')
    if len(nodes) > 1:
        for i in range(len(nodes) - 1):
            a = nodes[i]["label"].replace(" ", "_").replace("-", "_")[:30]
            b = nodes[i + 1]["label"].replace(" ", "_").replace("-", "_")[:30]
            lines.append(f"  {a} --> {b}")
    return "\n".join(lines), f"{diagram_type.title()} diagram"


async def summarize_modules(repository_id: str, module_path: str | None = None) -> tuple[str, list[dict]]:
    graph = get_graph_service()
    modules = graph.get_module_stats(repository_id)

    if module_path:
        modules = [m for m in modules if m["path"] == module_path]

    embedder = get_embedding_service()
    query = f"Explain module {module_path}" if module_path else "Summarize the main modules and architecture"
    sources = await embedder.search(repository_id, query, top_k=6)

    context = "\n\n".join(
        f"### {s['name']} ({s['file_path']})\n```python\n{s['content'][:800]}\n```"
        for s in sources
    )
    summary = await generate_answer(context, query)
    return sanitize_llm_output(summary), modules
