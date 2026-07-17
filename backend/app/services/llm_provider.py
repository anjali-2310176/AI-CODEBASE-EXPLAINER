import logging
from google import genai

from app.config import settings

logger = logging.getLogger(__name__)

_client: genai.Client | None = None


def get_gemini_client() -> genai.Client | None:
    """Return a cached Gemini client, or None if no API key is configured."""
    global _client
    if not settings.gemini_api_key:
        return None
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def check_llm_setup() -> dict:
    return {
        "llm_provider": "gemini-1.5-flash" if settings.gemini_api_key else "offline",
        "retrieval": "vector-cosine-similarity",
        "cost": "free (gemini-flash)",
        "lite_mode": settings.lite_mode,
        "graph_backend": settings.graph_backend if not settings.lite_mode else "memory",
    }


async def generate_answer(context: str, question: str) -> str:
    """Mocked response for portfolio recording without hitting API limits."""
    return f"""### Architecture Analysis

Based on the parsed repository, this codebase handles its functionality using well-structured modules.

**Key Components:**
- The primary data flow starts with the ingestion pipeline.
- It utilizes the newly migrated SQLite Code Graph for scalable persistent storage.
- All entities and relations are effectively captured through AST parsing.

*(Mocked response to bypass free-tier API quota for portfolio recording)*"""


def _offline_fallback(context: str, question: str) -> str:
    """Plain retrieval display used when GEMINI_API_KEY is absent."""
    lines = [
        f"**Question:** {question}\n",
        "**Retrieved context (set GEMINI_API_KEY for AI-generated answers):**\n",
    ]
    snippets = [s.strip() for s in context.split("```") if s.strip()][:4]
    for i, snippet in enumerate(snippets, 1):
        lines.append(f"{i}. {snippet[:400]}...\n")
    return "\n".join(lines)
