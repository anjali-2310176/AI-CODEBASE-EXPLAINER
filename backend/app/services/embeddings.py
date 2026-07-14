import logging
import re
from collections.abc import Iterator
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer

from app.config import settings
from app.db.models import RepositoryChunk
from app.services.entities import CodeChunk, CodeEntity
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_model = None
def get_model():
    global _model
    if _model is None:
        logger.info("Loading sentence-transformers model...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


class EmbeddingService:
    """Tiny SQLite-backed chunk store and retrieval service for the demo."""

    def entity_to_chunk(self, entity: CodeEntity) -> CodeChunk | None:
        if entity.entity_type.value in ("Import",):
            return None
        parts = [f"# {entity.entity_type.value}: {entity.name}"]
        if entity.file_path:
            parts.append(f"File: {entity.file_path}")
        if entity.signature:
            parts.append(f"Signature: {entity.signature}")
        if entity.docstring:
            parts.append(f"Docstring: {entity.docstring}")
        if entity.content:
            parts.append(entity.content)

        content = "\n".join(parts)
        if len(content.strip()) < 10:
            return None

        return CodeChunk(
            id=entity.id,
            repository_id=entity.repository_id,
            entity_id=entity.id,
            file_path=entity.file_path,
            entity_type=entity.entity_type.value,
            name=entity.name,
            content=content[:6000],
            line_start=entity.line_start,
            line_end=entity.line_end,
        )

    def iter_chunks(self, entities: list[CodeEntity]) -> Iterator[CodeChunk]:
        for entity in entities:
            chunk = self.entity_to_chunk(entity)
            if not chunk:
                continue
            yield chunk

    async def replace_repository_chunks(self, session: AsyncSession, repository_id: str, chunks: list[CodeChunk]) -> int:
        await session.execute(delete(RepositoryChunk).where(RepositoryChunk.repository_id == repository_id))
        if not chunks:
            return 0

        rows = [
            RepositoryChunk(
                id=chunk.id,
                repository_id=chunk.repository_id,
                file_path=chunk.file_path,
                entity_name=chunk.name,
                entity_type=chunk.entity_type,
                content=chunk.content,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
            )
            for chunk in chunks
        ]
        session.add_all(rows)
        return len(rows)

    def generate_embeddings(self, texts: list[str]) -> list[bytes]:
        if not texts:
            return []
        model = get_model()
        embeddings = model.encode(texts, convert_to_numpy=True)
        return [emb.astype(np.float32).tobytes() for emb in embeddings]

    async def search(self, repository_id: str, query: str, top_k: int | None = None) -> list[dict]:
        top_k = top_k or settings.retrieval_top_k

        from app.db.session import async_session_factory

        async with async_session_factory() as session:
            result = await session.execute(
                select(RepositoryChunk).where(RepositoryChunk.repository_id == repository_id)
            )
            chunks = result.scalars().all()

        if not chunks:
            return []

        model = get_model()
        query_embedding = model.encode([query], convert_to_numpy=True)[0].astype(np.float32)

        ranked = []
        for chunk in chunks:
            if chunk.embedding:
                chunk_emb = np.frombuffer(chunk.embedding, dtype=np.float32)
                score = np.dot(query_embedding, chunk_emb) / (np.linalg.norm(query_embedding) * np.linalg.norm(chunk_emb) + 1e-9)
            else:
                score = -1.0
            ranked.append((score, chunk))

        ranked.sort(key=lambda item: -item[0])

        results = []
        for score, chunk in ranked[:top_k]:
            results.append(
                {
                    "score": float(score),
                    "entity_id": chunk.id,
                    "name": chunk.entity_name,
                    "type": chunk.entity_type,
                    "file_path": chunk.file_path,
                    "content": chunk.content[:1500],
                    "line_start": chunk.line_start,
                    "line_end": chunk.line_end,
                }
            )
        return results


_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
