from dataclasses import dataclass, field
from enum import Enum


class EntityType(str, Enum):
    REPOSITORY = "Repository"
    MODULE = "Module"
    PACKAGE = "Package"
    CLASS = "Class"
    FUNCTION = "Function"
    METHOD = "Method"
    API = "API"
    DATABASE = "Database"
    DEPENDENCY = "Dependency"
    IMPORT = "Import"


class RelationType(str, Enum):
    CONTAINS = "CONTAINS"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    DEFINES = "DEFINES"
    DEPENDS_ON = "DEPENDS_ON"


@dataclass
class CodeEntity:
    id: str
    name: str
    entity_type: EntityType
    file_path: str
    repository_id: str
    line_start: int | None = None
    line_end: int | None = None
    signature: str | None = None
    docstring: str | None = None
    content: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class CodeRelation:
    source_id: str
    target_id: str
    relation_type: RelationType
    metadata: dict = field(default_factory=dict)


@dataclass
class CodeChunk:
    id: str
    repository_id: str
    entity_id: str
    file_path: str
    entity_type: str
    name: str
    content: str
    line_start: int | None = None
    line_end: int | None = None
