import logging
from typing import Any

from neo4j import GraphDatabase

from app.config import settings
from app.services.entities import CodeEntity, CodeRelation

logger = logging.getLogger(__name__)


class GraphService:
    def __init__(self) -> None:
        self._driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def close(self) -> None:
        self._driver.close()

    def ensure_constraints(self) -> None:
        with self._driver.session() as session:
            session.run(
                "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE"
            )
            session.run(
                "CREATE INDEX entity_repo_idx IF NOT EXISTS FOR (e:Entity) ON (e.repository_id)"
            )

    def clear_repository(self, repository_id: str) -> None:
        with self._driver.session() as session:
            session.run(
                "MATCH (e:Entity {repository_id: $repo_id}) DETACH DELETE e",
                repo_id=repository_id,
            )

    def upsert_entities_batch(self, entities: list[CodeEntity]) -> None:
        if not entities:
            return
        batch_size = settings.graph_batch_size
        with self._driver.session() as session:
            for i in range(0, len(entities), batch_size):
                batch = entities[i : i + batch_size]
                rows = [
                    {
                        "id": e.id,
                        "name": e.name,
                        "type": e.entity_type.value,
                        "file_path": e.file_path,
                        "repository_id": e.repository_id,
                        "line_start": e.line_start,
                        "line_end": e.line_end,
                        "signature": e.signature,
                        "docstring": e.docstring,
                    }
                    for e in batch
                ]
                session.run(
                    """
                    UNWIND $rows AS row
                    MERGE (e:Entity {id: row.id})
                    SET e.name = row.name,
                        e.type = row.type,
                        e.file_path = row.file_path,
                        e.repository_id = row.repository_id,
                        e.line_start = row.line_start,
                        e.line_end = row.line_end,
                        e.signature = row.signature,
                        e.docstring = row.docstring
                    """,
                    rows=rows,
                )

    def upsert_relations_batch(self, relations: list[CodeRelation]) -> None:
        if not relations:
            return
        batch_size = settings.graph_batch_size
        with self._driver.session() as session:
            for i in range(0, len(relations), batch_size):
                batch = relations[i : i + batch_size]
                by_type: dict[str, list[dict]] = {}
                for rel in batch:
                    by_type.setdefault(rel.relation_type.value, []).append(
                        {"source_id": rel.source_id, "target_id": rel.target_id}
                    )
                for rel_type, rows in by_type.items():
                    session.run(
                        f"""
                        UNWIND $rows AS row
                        MATCH (a:Entity {{id: row.source_id}})
                        MATCH (b:Entity {{id: row.target_id}})
                        MERGE (a)-[r:{rel_type}]->(b)
                        """,
                        rows=rows,
                    )

    def get_subgraph(
        self, repository_id: str, limit: int = 200, offset: int = 0
    ) -> dict[str, list[dict[str, Any]]]:
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity {repository_id: $repo_id})
                WITH e ORDER BY e.name
                SKIP $offset LIMIT $limit
                OPTIONAL MATCH (e)-[r]->(t:Entity {repository_id: $repo_id})
                RETURN e, collect({rel: type(r), target: t}) AS rels
                """,
                repo_id=repository_id,
                limit=limit,
                offset=offset,
            )
            nodes: dict[str, dict] = {}
            edges: list[dict] = []
            for record in result:
                e = record["e"]
                nodes[e["id"]] = {
                    "id": e["id"],
                    "label": e["name"],
                    "type": e["type"],
                    "file_path": e.get("file_path"),
                }
                for rel_info in record["rels"]:
                    if rel_info["target"]:
                        t = rel_info["target"]
                        nodes[t["id"]] = {
                            "id": t["id"],
                            "label": t["name"],
                            "type": t["type"],
                            "file_path": t.get("file_path"),
                        }
                        edges.append(
                            {"source": e["id"], "target": t["id"], "type": rel_info["rel"]}
                        )
            return {"nodes": list(nodes.values()), "edges": edges}

    def list_entities(
        self,
        repository_id: str,
        entity_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        with self._driver.session() as session:
            type_filter = "AND e.type = $type" if entity_type else ""
            result = session.run(
                f"""
                MATCH (e:Entity {{repository_id: $repo_id}})
                WHERE true {type_filter}
                RETURN e.id AS id, e.name AS name, e.type AS type,
                       e.file_path AS file_path, e.line_start AS line_start,
                       e.line_end AS line_end
                ORDER BY e.name
                SKIP $offset LIMIT $limit
                """,
                repo_id=repository_id,
                type=entity_type,
                limit=limit,
                offset=offset,
            )
            return [dict(r) for r in result]

    def get_module_stats(self, repository_id: str) -> list[dict]:
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity {repository_id: $repo_id})
                WHERE e.type IN ['Class', 'Function', 'Method']
                RETURN e.file_path AS module, e.type AS type, count(*) AS count
                ORDER BY module, type
                """,
                repo_id=repository_id,
            )
            module_map: dict[str, dict] = {}
            for r in result:
                mod = r["module"]
                if mod not in module_map:
                    module_map[mod] = {"path": mod, "classes": 0, "functions": 0, "methods": 0}
                key = r["type"].lower() + "s"
                if key in module_map[mod]:
                    module_map[mod][key] = r["count"]
            return list(module_map.values())


_graph_service: GraphService | None = None


def get_graph_service() -> GraphService:
    global _graph_service
    if _graph_service is None:
        _graph_service = GraphService()
        _graph_service.ensure_constraints()
    return _graph_service
