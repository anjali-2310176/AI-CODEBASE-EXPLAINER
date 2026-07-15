import logging
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CodeEdge, CodeNode
from app.services.entities import CodeEntity, CodeRelation

logger = logging.getLogger(__name__)


class GraphService:
    def __init__(self) -> None:
        pass

    def close(self) -> None:
        pass

    def ensure_constraints(self) -> None:
        pass

    async def clear_repository(self, session: AsyncSession, repository_id: str) -> None:
        await session.execute(delete(CodeEdge).where(CodeEdge.repository_id == repository_id))
        await session.execute(delete(CodeNode).where(CodeNode.repository_id == repository_id))
        await session.commit()

    async def upsert_entities_batch(
        self, session: AsyncSession, entities: list[CodeEntity]
    ) -> None:
        if not entities:
            return
            
        # Deduplicate in memory first
        seen = set()
        unique_entities = []
        for e in entities:
            if e.id not in seen:
                seen.add(e.id)
                unique_entities.append(e)
                
        values = [
            {
                "id": e.id,
                "repository_id": e.repository_id,
                "name": e.name,
                "node_type": e.entity_type.value,
                "file_path": e.file_path,
                "start_line": e.line_start,
                "end_line": e.line_end,
                "content": e.docstring or e.signature,
            }
            for e in unique_entities
        ]
        stmt = sqlite_insert(CodeNode).values(values).on_conflict_do_nothing()
        await session.execute(stmt)

    async def upsert_relations_batch(
        self, session: AsyncSession, repository_id: str, relations: list[CodeRelation]
    ) -> None:
        if not relations:
            return
            
        # Deduplicate relations
        seen = set()
        unique_rels = []
        for r in relations:
            key = f"{r.source_id}:{r.target_id}:{r.relation_type.value}"
            if key not in seen:
                seen.add(key)
                unique_rels.append(r)
                
        values = [
            {
                "repository_id": repository_id,
                "source_node_id": rel.source_id,
                "target_node_id": rel.target_id,
                "edge_type": rel.relation_type.value,
            }
            for rel in unique_rels
        ]
        stmt = sqlite_insert(CodeEdge).values(values).on_conflict_do_nothing()
        await session.execute(stmt)

    async def get_subgraph(
        self, session: AsyncSession, repository_id: str, limit: int = 200, offset: int = 0
    ) -> dict[str, list[dict[str, Any]]]:
        result = await session.execute(
            select(CodeNode)
            .where(CodeNode.repository_id == repository_id)
            .order_by(CodeNode.name)
            .limit(limit)
            .offset(offset)
        )
        page_nodes = result.scalars().all()
        node_ids = [n.id for n in page_nodes]

        nodes: dict[str, dict] = {}
        for e in page_nodes:
            nodes[e.id] = {
                "id": e.id,
                "label": e.name,
                "type": e.node_type,
                "file_path": e.file_path,
            }

        edges: list[dict] = []
        if node_ids:
            edge_result = await session.execute(
                select(CodeEdge).where(
                    CodeEdge.repository_id == repository_id,
                    CodeEdge.source_node_id.in_(node_ids)
                )
            )
            rel_edges = edge_result.scalars().all()
            target_ids = [r.target_node_id for r in rel_edges]

            if target_ids:
                target_result = await session.execute(
                    select(CodeNode).where(
                        CodeNode.repository_id == repository_id,
                        CodeNode.id.in_(target_ids)
                    )
                )
                targets = target_result.scalars().all()
                for t in targets:
                    nodes[t.id] = {
                        "id": t.id,
                        "label": t.name,
                        "type": t.node_type,
                        "file_path": t.file_path,
                    }
            for rel in rel_edges:
                edges.append(
                    {
                        "source": rel.source_node_id,
                        "target": rel.target_node_id,
                        "type": rel.edge_type,
                    }
                )

        return {"nodes": list(nodes.values()), "edges": edges}

    async def list_entities(
        self,
        session: AsyncSession,
        repository_id: str,
        entity_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        stmt = select(CodeNode).where(CodeNode.repository_id == repository_id)
        if entity_type:
            stmt = stmt.where(CodeNode.node_type == entity_type)
        stmt = stmt.order_by(CodeNode.name).limit(limit).offset(offset)
        result = await session.execute(stmt)
        nodes = result.scalars().all()
        return [
            {
                "id": n.id,
                "repository_id": n.repository_id,
                "name": n.name,
                "type": n.node_type,
                "file_path": n.file_path,
            }
            for n in nodes
        ]

    async def get_module_stats(self, session: AsyncSession, repository_id: str) -> list[dict]:
        stmt = (
            select(CodeNode.file_path, CodeNode.node_type, func.count(CodeNode.id))
            .where(
                CodeNode.repository_id == repository_id,
                CodeNode.node_type.in_(["Class", "Function", "Method"]),
            )
            .group_by(CodeNode.file_path, CodeNode.node_type)
        )
        result = await session.execute(stmt)
        rows = result.all()

        module_map: dict[str, dict] = {}
        for file_path, node_type, count in rows:
            if file_path not in module_map:
                module_map[file_path] = {
                    "path": file_path,
                    "classes": 0,
                    "functions": 0,
                    "methods": 0,
                }
            key = node_type.lower() + "s"
            module_map[file_path][key] += count

        return list(module_map.values())


_graph_service = None


def get_graph_service() -> GraphService:
    global _graph_service
    if _graph_service is None:
        _graph_service = GraphService()
        logger.info("Using SQLite graph storage")
    return _graph_service
