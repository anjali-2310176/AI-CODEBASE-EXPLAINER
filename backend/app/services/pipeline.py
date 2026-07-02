import asyncio
import gzip
import json
import logging
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import AnalysisJob, JobStatus, Repository
from app.observability.metrics import increment, observe
from app.security.file_safety import compute_file_hash
from app.services.clone import (
    analyze_structure,
    cleanup_clone,
    clone_repository,
    iter_python_files,
)
from app.services.embeddings import get_embedding_service
from app.services.entities import CodeEntity, CodeRelation, EntityType
from app.services.graph import get_graph_service
from app.services.parser.base import parser_registry
from app.services.parser import python_parser  # noqa: F401
from app.services.retention import save_structure_snapshot

logger = logging.getLogger(__name__)


class JobCancelledError(Exception):
    pass


def _check_cancelled(cancel_event: asyncio.Event | None) -> None:
    if cancel_event and cancel_event.is_set():
        raise JobCancelledError("Job cancelled by user")


class IngestionPipeline:
    """Streaming pipeline: Clone → Parse (file-by-file) → Graph (batched) → Index → Cleanup."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=settings.parse_workers)

    async def run(
        self,
        session: AsyncSession,
        url: str,
        branch: str | None = None,
        cancel_event: asyncio.Event | None = None,
        job_id: str | None = None,
    ) -> str:
        import time
        start = time.perf_counter()
        job_id = job_id or str(uuid.uuid4())
        repo_id: str | None = None
        local_path: Path | None = None

        try:
            _check_cancelled(cancel_event)
            repo_id, name, local_path = await asyncio.get_event_loop().run_in_executor(
                None, lambda: clone_repository(url, branch)
            )

            repo = await self._upsert_repo(session, repo_id, url, name, local_path, branch)
            job = await self._upsert_job(session, job_id, repo_id, JobStatus.CLONING, "clone", 10)

            structure = analyze_structure(local_path)
            save_structure_snapshot(repo_id, structure)

            _check_cancelled(cancel_event)
            repo.status = JobStatus.PARSING
            job.status = JobStatus.PARSING
            job.stage = "parse"
            job.progress = 20
            await session.commit()

            parser = parser_registry.get("python")
            existing_manifest = get_embedding_service().load_file_manifest(repo_id)
            file_manifest: dict[str, str] = {}
            entity_buffer: list[CodeEntity] = []
            relation_buffer: list[CodeRelation] = []
            file_count = 0
            entity_count = 0

            entity_spill_path = Path(settings.metadata_dir) / repo_id
            entity_spill_path.mkdir(parents=True, exist_ok=True)
            entity_spill_file = entity_spill_path / "entities.jsonl.gz"
            spill = gzip.open(entity_spill_file, "wt", encoding="utf-8")

            graph = get_graph_service()
            graph.clear_repository(repo_id)

            for file_path in iter_python_files(local_path):
                _check_cancelled(cancel_event)

                rel_path = str(file_path.relative_to(local_path))
                file_hash = await asyncio.get_event_loop().run_in_executor(
                    None, compute_file_hash, file_path
                )
                file_manifest[rel_path] = file_hash

                if existing_manifest.get(rel_path) == file_hash:
                    continue

                entities, relations = await asyncio.get_event_loop().run_in_executor(
                    self._executor,
                    parser.parse_file,
                    file_path,
                    local_path,
                    repo_id,
                )
                entity_buffer.extend(entities)
                relation_buffer.extend(relations)
                for e in entities:
                    spill.write(
                        json.dumps({
                            "id": e.id, "name": e.name,
                            "entity_type": e.entity_type.value,
                            "file_path": e.file_path,
                            "repository_id": e.repository_id,
                            "line_start": e.line_start, "line_end": e.line_end,
                            "signature": e.signature, "docstring": e.docstring,
                            "content": e.content,
                        }) + "\n"
                    )
                file_count += 1
                entity_count += len(entities)

                if len(entity_buffer) >= settings.graph_batch_size:
                    graph.upsert_entities_batch(entity_buffer)
                    graph.upsert_relations_batch(relation_buffer)
                    entity_buffer.clear()
                    relation_buffer.clear()

                if file_count % settings.parse_batch_size == 0:
                    job.progress = 20 + int(40 * file_count / settings.max_file_count)
                    await session.commit()

            spill.close()

            if entity_buffer:
                graph.upsert_entities_batch(entity_buffer)
                graph.upsert_relations_batch(relation_buffer)
            entity_buffer.clear()
            relation_buffer.clear()

            repo.file_count = file_count
            repo.entity_count = entity_count

            _check_cancelled(cancel_event)
            repo.status = JobStatus.INDEXING
            job.status = JobStatus.INDEXING
            job.stage = "index"
            job.progress = 70
            await session.commit()

            embedder = get_embedding_service()
            embedder.save_file_manifest(repo_id, file_manifest)

            def chunk_generator() -> Iterator:
                def _entity_from_row(row: dict) -> CodeEntity:
                    return CodeEntity(
                        id=row["id"], name=row["name"],
                        entity_type=EntityType(row["entity_type"]),
                        file_path=row["file_path"],
                        repository_id=row["repository_id"],
                        line_start=row.get("line_start"),
                        line_end=row.get("line_end"),
                        signature=row.get("signature"),
                        docstring=row.get("docstring"),
                        content=row.get("content"),
                    )

                if entity_spill_file.exists():
                    with gzip.open(entity_spill_file, "rt", encoding="utf-8") as f:
                        batch: list[CodeEntity] = []
                        for line in f:
                            entity = _entity_from_row(json.loads(line))
                            batch.append(entity)
                            if len(batch) >= settings.embed_batch_size:
                                yield from embedder.iter_chunks(batch)
                                batch.clear()
                        if batch:
                            yield from embedder.iter_chunks(batch)
                    entity_spill_file.unlink(missing_ok=True)

            indexed = await asyncio.get_event_loop().run_in_executor(
                None, embedder.build_index_streaming, repo_id, chunk_generator()
            )

            if settings.delete_clone_after_index and local_path:
                await asyncio.get_event_loop().run_in_executor(None, cleanup_clone, local_path)
                repo.local_path = ""

            repo.status = JobStatus.COMPLETED
            job.status = JobStatus.COMPLETED
            job.stage = "done"
            job.progress = 100
            await session.commit()

            observe("ingestion_duration_ms", (time.perf_counter() - start) * 1000)
            increment("repositories_indexed")
            logger.info(
                "Ingestion complete for %s: %d files, %d entities, %d chunks",
                name, file_count, entity_count, indexed,
            )
            return repo_id

        except JobCancelledError:
            await self._mark_failed(session, repo_id, job_id, "Cancelled by user", JobStatus.FAILED)
            raise
        except Exception as e:
            logger.exception("Ingestion failed for %s", url)
            await self._mark_failed(session, repo_id, job_id, str(e), JobStatus.FAILED)
            raise

    async def _upsert_repo(
        self, session, repo_id, url, name, local_path, branch
    ) -> Repository:
        result = await session.execute(select(Repository).where(Repository.id == repo_id))
        repo = result.scalar_one_or_none()
        if not repo:
            repo = Repository(
                id=repo_id,
                url=url,
                name=name,
                local_path=str(local_path),
                default_branch=branch or "main",
                status=JobStatus.CLONING,
            )
            session.add(repo)
        else:
            repo.status = JobStatus.CLONING
            repo.error_message = None
            repo.local_path = str(local_path)
        await session.commit()
        return repo

    async def _upsert_job(self, session, job_id, repo_id, status, stage, progress) -> AnalysisJob:
        result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            job = AnalysisJob(id=job_id, repository_id=repo_id, status=status, stage=stage, progress=progress)
            session.add(job)
        else:
            job.status = status
            job.stage = stage
            job.progress = progress
            job.error_message = None
        await session.commit()
        return job

    async def _mark_failed(self, session, repo_id, job_id, error, status):
        if repo_id:
            result = await session.execute(select(Repository).where(Repository.id == repo_id))
            repo = result.scalar_one_or_none()
            if repo:
                repo.status = status
                repo.error_message = error
        result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == job_id))
        job = result.scalar_one_or_none()
        if job:
            job.status = status
            job.error_message = error
        await session.commit()


ingestion_pipeline = IngestionPipeline()
