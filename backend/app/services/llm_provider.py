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
    """
    Generate a grounded answer using Gemini via RAG.
    Falls back to offline mode if GEMINI_API_KEY is not set.
    """
    client = get_gemini_client()

    if not client:
        return _offline_fallback(context, question)

    prompt = (
        "You are an expert AI Codebase Explainer.\n"
        "Answer the user's question based ONLY on the retrieved code context below.\n"
        "If the context does not contain enough information, say so clearly.\n"
        "Use markdown and code blocks where relevant.\n\n"
        f"## Retrieved Code Context\n{context}\n\n"
        f"## Question\n{question}\n\n"
        "## Answer"
    )

    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return response.text
    except Exception as e:
        logger.exception("Gemini API call failed")
        return f"**Gemini API error:** {e}\n\n" + _offline_fallback(context, question)


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
