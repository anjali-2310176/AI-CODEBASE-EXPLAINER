import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import AnalysisJob, JobStatus, Repository
from app.observability.metrics import increment, observe
from app.services.clone import (
    analyze_structure,
    cleanup_clone,
    clone_repository,
    iter_python_files,
    repo_id_from_url,
)
from app.services.embeddings import get_embedding_service
from app.services.entities import CodeEntity, CodeRelation
from app.services.graph import get_graph_service
from app.services.parser.base import parser_registry
from app.services.parser import python_parser  # noqa: F401
from app.services.retention import save_structure_snapshot
from app.db.models import RepositoryChunk

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
        job_id = job_id or repo_id_from_url(url)
        repo_id: str | None = None
        local_path: Path | None = None

        try:
            embedder = get_embedding_service()
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
            entity_buffer: list[CodeEntity] = []
            relation_buffer: list[CodeRelation] = []
            chunk_buffer: list[RepositoryChunk] = []
            file_count = 0
            entity_count = 0
            chunk_count = 0

            graph = get_graph_service()
            await graph.clear_repository(session, repo_id)
            await session.execute(delete(RepositoryChunk).where(RepositoryChunk.repository_id == repo_id))
            await session.commit()

            for file_path in iter_python_files(local_path):
                _check_cancelled(cancel_event)

                entities, relations = await asyncio.get_event_loop().run_in_executor(
                    self._executor,
                    parser.parse_file,
                    file_path,
                    local_path,
                    repo_id,
                )
                entity_buffer.extend(entities)
                relation_buffer.extend(relations)
                chunks_to_add = list(embedder.iter_chunks(entities))
                if chunks_to_add:
                    texts = [chunk.content for chunk in chunks_to_add]
                    embeddings = await asyncio.get_event_loop().run_in_executor(
                        self._executor, embedder.generate_embeddings, texts
                    )
                    
                    for chunk, emb in zip(chunks_to_add, embeddings):
                        chunk_buffer.append(
                            RepositoryChunk(
                                id=chunk.id,
                                repository_id=chunk.repository_id,
                                file_path=chunk.file_path,
                                entity_name=chunk.name,
                                entity_type=chunk.entity_type,
                                content=chunk.content,
                                line_start=chunk.line_start,
                                line_end=chunk.line_end,
                                embedding=emb,
                            )
                        )
                file_count += 1
                entity_count += len(entities)

                if len(entity_buffer) > 200:
                    await graph.upsert_entities_batch(session, entity_buffer)
                    entity_buffer.clear()
                if len(relation_buffer) > 500:
                    await graph.upsert_relations_batch(session, repo_id, relation_buffer)
                    relation_buffer.clear()
                if len(chunk_buffer) > 100:
                    session.add_all(chunk_buffer)
                    await session.commit()
                    chunk_count += len(chunk_buffer)
                    chunk_buffer.clear()

                if file_count % settings.parse_batch_size == 0:
                    job.progress = 20 + int(40 * file_count / settings.max_file_count)
                    await session.commit()

            if entity_buffer:
                await graph.upsert_entities_batch(session, entity_buffer)
            if relation_buffer:
                await graph.upsert_relations_batch(session, repo_id, relation_buffer)
            entity_buffer.clear()
            relation_buffer.clear()

            if chunk_buffer:
                session.add_all(chunk_buffer)
                await session.commit()
                chunk_count += len(chunk_buffer)
                chunk_buffer.clear()

            repo.file_count = file_count
            repo.entity_count = entity_count

            _check_cancelled(cancel_event)
            repo.status = JobStatus.INDEXING
            job.status = JobStatus.INDEXING
            job.stage = "index"
            job.progress = 70
            await session.commit()

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
                name, file_count, entity_count, chunk_count,
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
