import logging
from typing import Any

from app.services.entities import CodeEntity, CodeRelation

logger = logging.getLogger(__name__)


class GraphService:
    def __init__(self) -> None:
        self._entities: dict[str, dict] = {}
        self._relations: list[dict] = []

    def close(self) -> None:
        pass

    def ensure_constraints(self) -> None:
        pass

    def clear_repository(self, repository_id: str) -> None:
        to_delete = {
            eid for eid, e in self._entities.items() if e.get("repository_id") == repository_id
        }
        for eid in to_delete:
            del self._entities[eid]
        self._relations = [
            r for r in self._relations
            if r["source_id"] not in to_delete and r["target_id"] not in to_delete
        ]

    def upsert_entities_batch(self, entities: list[CodeEntity]) -> None:
        for entity in entities:
            self._entities[entity.id] = {
                "id": entity.id,
                "name": entity.name,
                "type": entity.entity_type.value,
                "file_path": entity.file_path,
                "repository_id": entity.repository_id,
                "line_start": entity.line_start,
                "line_end": entity.line_end,
                "signature": entity.signature,
                "docstring": entity.docstring,
            }

    def upsert_relations_batch(self, relations: list[CodeRelation]) -> None:
        for rel in relations:
            self._relations.append({
                "source_id": rel.source_id,
                "target_id": rel.target_id,
                "type": rel.relation_type.value,
            })

    def get_subgraph(
        self, repository_id: str, limit: int = 200, offset: int = 0
    ) -> dict[str, list[dict[str, Any]]]:
        repo_entities = [e for e in self._entities.values() if e["repository_id"] == repository_id]
        repo_entities.sort(key=lambda x: x["name"])
        page = repo_entities[offset : offset + limit]

        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        for e in page:
            nodes[e["id"]] = {
                "id": e["id"],
                "label": e["name"],
                "type": e["type"],
                "file_path": e.get("file_path"),
            }
            for rel in self._relations:
                if rel["source_id"] == e["id"] and rel["target_id"] in self._entities:
                    t = self._entities[rel["target_id"]]
                    if t["repository_id"] == repository_id:
                        nodes[t["id"]] = {
                            "id": t["id"],
                            "label": t["name"],
                            "type": t["type"],
                            "file_path": t.get("file_path"),
                        }
                        edges.append({
                            "source": rel["source_id"],
                            "target": rel["target_id"],
                            "type": rel["type"],
                        })
        return {"nodes": list(nodes.values()), "edges": edges}

    def list_entities(
        self,
        repository_id: str,
        entity_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        items = [
            e for e in self._entities.values()
            if e["repository_id"] == repository_id
            and (entity_type is None or e["type"] == entity_type)
        ]
        items.sort(key=lambda x: x["name"])
        return items[offset : offset + limit]

    def get_module_stats(self, repository_id: str) -> list[dict]:
        module_map: dict[str, dict] = {}
        for e in self._entities.values():
            if e["repository_id"] != repository_id:
                continue
            if e["type"] not in ("Class", "Function", "Method"):
                continue
            mod = e["file_path"]
            if mod not in module_map:
                module_map[mod] = {"path": mod, "classes": 0, "functions": 0, "methods": 0}
            key = e["type"].lower() + "s"
            if key in module_map[mod]:
                module_map[mod][key] += 1
        return list(module_map.values())


_graph_service = None


def get_graph_service():
    global _graph_service
    if _graph_service is None:
        _graph_service = GraphService()
        _graph_service.ensure_constraints()
        logger.info("Using in-memory graph (lite mode)")
    return _graph_service
