import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import AnalysisJob, JobStatus, Repository
from app.db.session import async_session_factory, get_session
from app.observability.metrics import increment
from app.schemas import (
    ChatRequest,
    ChatResponse,
    DiagramRequest,
    DiagramResponse,
    GraphResponse,
    IngestRequest,
    JobResponse,
    ModuleSummaryRequest,
    ModuleSummaryResponse,
    PaginatedResponse,
    ReadmeRequest,
    ReadmeResponse,
    RepositoryResponse,
    StructureResponse,
)
from app.security.rate_limit import get_client_id, rate_limiter
from app.security.validation import validate_repo_id
from app.services.agent import ask_question, generate_diagram, generate_readme, summarize_modules
from app.services.clone import analyze_structure, repo_id_from_url
from app.services.jobs.queue import job_queue
from app.services.pipeline import ingestion_pipeline
from app.services.graph import get_graph_service
from app.services.retention import load_structure_snapshot

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["repositories"])


async def _rate_limit(request: Request) -> None:
    rate_limiter.check(get_client_id(request))


def _make_ingestion_coro(url: str, branch: str | None, job_id: str, cancel_event_holder: dict):
    async def run():
        cancel_event = cancel_event_holder.get("event")
        async with async_session_factory() as session:
            return await ingestion_pipeline.run(
                session, url, branch, cancel_event=cancel_event, job_id=job_id
            )

    return run


@router.post("/ingest", response_model=JobResponse, dependencies=[Depends(_rate_limit)])
async def ingest_repository(
    request: IngestRequest,
    session: AsyncSession = Depends(get_session),
):
    url = str(request.url)
    repo_id = repo_id_from_url(url)
    job_id = repo_id
    cancel_holder: dict = {}

    task_id = job_queue.enqueue(
        repo_id,
        _make_ingestion_coro(url, request.branch, job_id, cancel_holder),
    )
    task = job_queue.get_task(task_id)
    if task:
        cancel_holder["event"] = task.cancel_event

    result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == job_id))
    existing_job = result.scalar_one_or_none()
    if not existing_job:
        job = AnalysisJob(
            id=job_id,
            repository_id=repo_id,
            status=JobStatus.PENDING,
            stage="queued",
            progress=0,
        )
        session.add(job)
        await session.commit()

    increment("ingest_requests")
    result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=500, detail="Job creation failed")
    return JobResponse(
        id=job.id,
        repository_id=job.repository_id,
        status=job.status.value,
        stage=job.stage,
        progress=job.progress,
    )


@router.get("/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(_rate_limit)])
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)):
    validate_repo_id(job_id)
    result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(
        id=job.id,
        repository_id=job.repository_id,
        status=job.status.value,
        stage=job.stage,
        progress=job.progress,
        retry_count=job.retry_count,
        cancelled=job.cancelled,
        error_message=job.error_message,
    )


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(_rate_limit)])
async def cancel_job(job_id: str, session: AsyncSession = Depends(get_session)):
    validate_repo_id(job_id)
    cancelled = job_queue.cancel(job_id)
    result = await session.execute(select(AnalysisJob).where(AnalysisJob.id == job_id))
    job = result.scalar_one_or_none()
    if job:
        job.cancelled = True
        job.status = JobStatus.CANCELLED
        await session.commit()
    return {"cancelled": cancelled}


@router.get("/repositories", response_model=PaginatedResponse[RepositoryResponse], dependencies=[Depends(_rate_limit)])
async def list_repositories(
    page: int = Query(1, ge=1),
    page_size: int = Query(default=settings.default_page_size, ge=1, le=settings.max_page_size),
    session: AsyncSession = Depends(get_session),
):
    offset = (page - 1) * page_size
    total_result = await session.execute(select(func.count()).select_from(Repository))
    total = total_result.scalar() or 0

    result = await session.execute(
        select(Repository).order_by(Repository.created_at.desc()).offset(offset).limit(page_size)
    )
    repos = result.scalars().all()
    items = [
        RepositoryResponse(
            id=r.id, url=r.url, name=r.name, status=r.status.value,
            file_count=r.file_count, entity_count=r.entity_count, error_message=r.error_message,
        )
        for r in repos
    ]
    return PaginatedResponse(
        items=items, total=total, page=page, page_size=page_size,
        has_more=(offset + page_size) < total,
    )


@router.get("/repositories/{repo_id}", response_model=RepositoryResponse, dependencies=[Depends(_rate_limit)])
async def get_repository(repo_id: str, session: AsyncSession = Depends(get_session)):
    validate_repo_id(repo_id)
    result = await session.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return RepositoryResponse(
        id=repo.id, url=repo.url, name=repo.name, status=repo.status.value,
        file_count=repo.file_count, entity_count=repo.entity_count, error_message=repo.error_message,
    )


@router.get("/repositories/{repo_id}/structure", response_model=StructureResponse, dependencies=[Depends(_rate_limit)])
async def get_structure(repo_id: str, session: AsyncSession = Depends(get_session)):
    validate_repo_id(repo_id)
    result = await session.execute(select(Repository).where(Repository.id == repo_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if repo.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Repository analysis not complete")

    structure = load_structure_snapshot(repo_id)
    if not structure and repo.local_path:
        structure = analyze_structure(Path(repo.local_path))
    if not structure:
        raise HTTPException(status_code=404, detail="Structure snapshot not found")

    return StructureResponse(
        repository_id=repo_id,
        root=structure["root"],
        total_files=structure["total_files"],
        total_directories=structure["total_directories"],
    )


@router.get("/repositories/{repo_id}/graph", response_model=GraphResponse, dependencies=[Depends(_rate_limit)])
async def get_graph(
    repo_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    validate_repo_id(repo_id)
    result = await session.execute(select(Repository).where(Repository.id == repo_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Repository not found")

    offset = (page - 1) * page_size
    graph = get_graph_service()
    data = graph.get_subgraph(repo_id, limit=page_size, offset=offset)
    return GraphResponse(
        nodes=data["nodes"], edges=data["edges"],
        page=page, page_size=page_size,
        has_more=len(data["nodes"]) >= page_size,
    )


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(_rate_limit)])
async def chat(request: ChatRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Repository).where(Repository.id == request.repository_id))
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    if repo.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Repository analysis not complete")

    response = ask_question(request.repository_id, request.question)
    return ChatResponse(answer=response["answer"], sources=response["sources"])


@router.post("/diagram", response_model=DiagramResponse, dependencies=[Depends(_rate_limit)])
async def diagram(request: DiagramRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Repository).where(Repository.id == request.repository_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Repository not found")
    mermaid, description = generate_diagram(request.repository_id, request.diagram_type)
    return DiagramResponse(mermaid=mermaid, description=description)


@router.post("/readme", response_model=ReadmeResponse, dependencies=[Depends(_rate_limit)])
async def readme(request: ReadmeRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Repository).where(Repository.id == request.repository_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Repository not found")
    content = generate_readme(request.repository_id)
    return ReadmeResponse(content=content)


@router.post("/summarize", response_model=ModuleSummaryResponse, dependencies=[Depends(_rate_limit)])
async def summarize(request: ModuleSummaryRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Repository).where(Repository.id == request.repository_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Repository not found")
    summary, modules = summarize_modules(request.repository_id, request.module_path)
    return ModuleSummaryResponse(summary=summary, modules=modules)
