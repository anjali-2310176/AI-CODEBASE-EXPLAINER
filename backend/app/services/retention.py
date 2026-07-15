import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import AnalysisJob, Repository
from app.services.graph import get_graph_service

logger = logging.getLogger(__name__)


async def cleanup_expired_repositories(session: AsyncSession) -> int:
    """Remove repositories older than retention_days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
    result = await session.execute(
        select(Repository).where(Repository.updated_at < cutoff)
    )
    repos = result.scalars().all()
    removed = 0

    graph = get_graph_service()
    for repo in repos:
        try:
            graph.clear_repository(repo.id)
            _remove_repo_data(repo.id, repo.local_path)
            await session.execute(delete(AnalysisJob).where(AnalysisJob.repository_id == repo.id))
            await session.delete(repo)
            removed += 1
        except Exception:
            logger.exception("Failed to clean up repository %s", repo.id)

    if removed:
        await session.commit()
        logger.info("Retention policy removed %d repositories", removed)
    return removed


def _remove_repo_data(repo_id: str, local_path: str | None) -> None:
    path = Path(settings.metadata_dir) / repo_id
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    if local_path:
        lp = Path(local_path)
        if lp.exists():
            shutil.rmtree(lp, ignore_errors=True)


def save_structure_snapshot(repo_id: str, structure: dict) -> str:
    path = Path(settings.metadata_dir) / repo_id
    path.mkdir(parents=True, exist_ok=True)
    out = path / "structure.json"
    with open(out, "w") as f:
        json.dump(structure, f)
    return str(out)


def load_structure_snapshot(repo_id: str) -> dict | None:
    path = Path(settings.metadata_dir) / repo_id / "structure.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)
