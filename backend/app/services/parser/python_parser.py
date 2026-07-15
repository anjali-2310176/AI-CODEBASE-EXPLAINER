import hashlib
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from app.security.file_safety import read_text_safe
from app.security.sanitization import redact_secrets
from app.services.entities import CodeEntity, CodeRelation, EntityType, RelationType
from app.services.parser.base import CodeParser, parser_registry


PY_LANGUAGE = Language(tspython.language())


def _entity_id(repo_id: str, file_path: str, name: str, entity_type: str, parent_id: str = "") -> str:
    key = f"{repo_id}:{file_path}:{entity_type}:{name}:{parent_id}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _node_text(source: bytes, node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _get_docstring(source: bytes, body_node) -> str | None:
    if not body_node or body_node.child_count == 0:
        return None
    first = body_node.children[0]
    if first.type == "expression_statement":
        expr = first.children[0] if first.children else None
        if expr and expr.type == "string":
            text = _node_text(source, expr)
            return text.strip('"""').strip("'''").strip('"').strip("'")
    return None


class PythonParser(CodeParser):
    @property
    def language(self) -> str:
        return "python"

    def parse_file(
        self, file_path: Path, repo_path: Path, repository_id: str
    ) -> tuple[list[CodeEntity], list[CodeRelation]]:
        rel_path = str(file_path.relative_to(repo_path))
        text = read_text_safe(file_path)
        source = text.encode("utf-8")
        parser = Parser(PY_LANGUAGE)
        tree = parser.parse(source)
        root = tree.root_node

        entities: list[CodeEntity] = []
        relations: list[CodeRelation] = []

        module_id = _entity_id(repository_id, rel_path, rel_path, "Module", "")
        module_entity = CodeEntity(
            id=module_id,
            name=file_path.stem,
            entity_type=EntityType.MODULE,
            file_path=rel_path,
            repository_id=repository_id,
            line_start=1,
            line_end=text.count("\n") + 1,
            content=redact_secrets(text[:8000]),
        )
        entities.append(module_entity)

        class_ids: dict[str, str] = {}

        def walk(node, parent_class_id: str | None = None):
            if node.type == "import_statement" or node.type == "import_from_statement":
                import_text = _node_text(source, node)
                import_id = _entity_id(repository_id, rel_path, import_text, "Import", module_id)
                entities.append(
                    CodeEntity(
                        id=import_id,
                        name=import_text,
                        entity_type=EntityType.IMPORT,
                        file_path=rel_path,
                        repository_id=repository_id,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        content=import_text,
                    )
                )
                relations.append(
                    CodeRelation(source_id=module_id, target_id=import_id, relation_type=RelationType.IMPORTS)
                )

            elif node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    return
                class_name = _node_text(source, name_node)
                class_id = _entity_id(repository_id, rel_path, class_name, "Class", module_id)
                class_ids[class_name] = class_id
                body = node.child_by_field_name("body")
                docstring = _get_docstring(source, body) if body else None
                entities.append(
                    CodeEntity(
                        id=class_id,
                        name=class_name,
                        entity_type=EntityType.CLASS,
                        file_path=rel_path,
                        repository_id=repository_id,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        docstring=docstring,
                        content=redact_secrets(_node_text(source, node)[:4000]),
                    )
                )
                relations.append(
                    CodeRelation(source_id=module_id, target_id=class_id, relation_type=RelationType.CONTAINS)
                )
                superclasses = node.child_by_field_name("superclasses")
                if superclasses:
                    for child in superclasses.children:
                        if child.type == "identifier":
                            parent_name = _node_text(source, child)
                            parent_id = _entity_id(repository_id, rel_path, parent_name, "Class", module_id)
                            relations.append(
                                CodeRelation(
                                    source_id=class_id, target_id=parent_id, relation_type=RelationType.INHERITS
                                )
                            )
                for child in node.children:
                    walk(child, class_id)

            elif node.type == "function_definition":
                name_node = node.child_by_field_name("name")
                if not name_node:
                    return
                func_name = _node_text(source, name_node)
                is_method = parent_class_id is not None
                etype = EntityType.METHOD if is_method else EntityType.FUNCTION
                parent_id = parent_class_id or module_id
                func_id = _entity_id(repository_id, rel_path, func_name, etype.value, parent_id)
                body = node.child_by_field_name("body")
                docstring = _get_docstring(source, body) if body else None
                params = node.child_by_field_name("parameters")
                signature = f"{func_name}{_node_text(source, params)}" if params else func_name
                entities.append(
                    CodeEntity(
                        id=func_id,
                        name=func_name,
                        entity_type=etype,
                        file_path=rel_path,
                        repository_id=repository_id,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        signature=signature,
                        docstring=docstring,
                        content=redact_secrets(_node_text(source, node)[:4000]),
                    )
                )
                relations.append(
                    CodeRelation(source_id=parent_id, target_id=func_id, relation_type=RelationType.DEFINES)
                )

            elif node.type in ("decorated_definition",):
                for child in node.children:
                    walk(child, parent_class_id)
            else:
                for child in node.children:
                    walk(child, parent_class_id)

        walk(root)
        return entities, relations


parser_registry.register(PythonParser())
