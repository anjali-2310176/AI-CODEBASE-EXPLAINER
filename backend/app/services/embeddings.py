import gzip
import hashlib
import json
import logging
import pickle
from collections.abc import Iterator
from pathlib import Path

import faiss
import numpy as np
from openai import OpenAI

from app.config import settings
from app.observability.metrics import increment, observe
from app.services.entities import CodeChunk, CodeEntity

logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self) -> None:
        self._client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self._dimension = 1536

    def _index_path(self, repository_id: str) -> Path:
        path = Path(settings.index_dir) / repository_id
        path.mkdir(parents=True, exist_ok=True)
        return path

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
        seen_hashes: set[str] = set()
        for entity in entities:
            chunk = self.entity_to_chunk(entity)
            if not chunk:
                continue
            content_hash = hashlib.sha256(chunk.content.encode()).hexdigest()
            if content_hash in seen_hashes:
                continue
            seen_hashes.add(content_hash)
            yield chunk

    def _embed_texts(self, texts: list[str]) -> np.ndarray:
        if not self._client:
            raise RuntimeError("OpenAI API key not configured")
        start = __import__("time").perf_counter()
        response = self._client.embeddings.create(
            model=settings.embedding_model,
            input=texts,
        )
        observe("embedding_latency_ms", (__import__("time").perf_counter() - start) * 1000)
        increment("embeddings_generated", len(texts))
        return np.array([item.embedding for item in response.data], dtype=np.float32)

    def _save_chunks_compressed(self, path: Path, chunks: list[CodeChunk]) -> None:
        data = pickle.dumps(chunks)
        with gzip.open(path, "wb", compresslevel=6) as f:
            f.write(data)

    def _load_chunks_compressed(self, path: Path) -> list[CodeChunk]:
        with gzip.open(path, "rb") as f:
            return pickle.load(f)

    def build_index_streaming(self, repository_id: str, chunk_iter: Iterator[CodeChunk]) -> int:
        """Build FAISS index from chunk iterator — never holds all chunks in RAM."""
        index_dir = self._index_path(repository_id)
        batch_size = settings.embed_batch_size
        all_chunks: list[CodeChunk] = []
        all_vectors: list[np.ndarray] = []

        batch: list[CodeChunk] = []
        for chunk in chunk_iter:
            batch.append(chunk)
            if len(batch) >= batch_size:
                vectors = self._embed_texts([c.content for c in batch])
                all_vectors.append(vectors)
                all_chunks.extend(batch)
                batch = []
                del vectors

        if batch:
            vectors = self._embed_texts([c.content for c in batch])
            all_vectors.append(vectors)
            all_chunks.extend(batch)

        if not all_chunks:
            return 0

        matrix = np.vstack(all_vectors)
        del all_vectors

        index = faiss.IndexFlatIP(self._dimension)
        faiss.normalize_L2(matrix)
        index.add(matrix)
        del matrix

        faiss.write_index(index, str(index_dir / "index.faiss"))
        self._save_chunks_compressed(index_dir / "chunks.pkl.gz", all_chunks)

        metadata = {"count": len(all_chunks), "dimension": self._dimension}
        with open(index_dir / "metadata.json", "w") as f:
            json.dump(metadata, f)

        logger.info("Built index for %s: %d chunks", repository_id, len(all_chunks))
        return len(all_chunks)

    def save_file_manifest(self, repository_id: str, manifest: dict[str, str]) -> None:
        path = self._index_path(repository_id) / "file_manifest.json"
        with open(path, "w") as f:
            json.dump(manifest, f)

    def load_file_manifest(self, repository_id: str) -> dict[str, str]:
        path = self._index_path(repository_id) / "file_manifest.json"
        if not path.exists():
            return {}
        with open(path) as f:
            return json.load(f)

    def search(self, repository_id: str, query: str, top_k: int | None = None) -> list[dict]:
        top_k = top_k or settings.retrieval_top_k
        index_dir = self._index_path(repository_id)

        index_file = index_dir / "index.faiss"
        chunks_file = index_dir / "chunks.pkl.gz"
        legacy_chunks = index_dir / "chunks.pkl"

        if not index_file.exists():
            return []

        if chunks_file.exists():
            chunks = self._load_chunks_compressed(chunks_file)
        elif legacy_chunks.exists():
            with open(legacy_chunks, "rb") as f:
                chunks = pickle.load(f)
        else:
            return []

        index = faiss.read_index(str(index_file))
        query_vec = self._embed_texts([query])
        faiss.normalize_L2(query_vec)
        scores, indices = index.search(query_vec, min(top_k, len(chunks)))

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            chunk = chunks[idx]
            results.append(
                {
                    "score": float(score),
                    "entity_id": chunk.entity_id,
                    "name": chunk.name,
                    "type": chunk.entity_type,
                    "file_path": chunk.file_path,
                    "content": chunk.content[:1500],
                    "line_start": chunk.line_start,
                    "line_end": chunk.line_end,
                }
            )
        increment("searches_performed")
        return results


_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
