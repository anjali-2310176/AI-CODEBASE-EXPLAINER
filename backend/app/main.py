import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.db.session import init_db
from app.middleware.logging import StructuredLoggingMiddleware
from app.observability.metrics import get_metrics
from app.services.jobs.queue import job_queue
from app.services.retention import cleanup_expired_repositories
from app.db.session import async_session_factory

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    job_queue.start()
    logger.info("Application started")

    async with async_session_factory() as session:
        try:
            removed = await cleanup_expired_repositories(session)
            if removed:
                logger.info("Retention cleanup: removed %d repos", removed)
        except Exception:
            logger.exception("Retention cleanup failed")

    yield

    await job_queue.stop()
    logger.info("Application shutdown")


app = FastAPI(
    title="AI Codebase Explainer",
    description="Ingest, analyze, and query GitHub repositories with AI",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}


@app.get("/metrics")
async def metrics():
    return get_metrics()
