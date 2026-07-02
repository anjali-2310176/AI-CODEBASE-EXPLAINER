from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.config import settings
from app.security.sanitization import sanitize_user_question
from app.security.validation import validate_branch_name, validate_github_url, validate_repo_id

T = TypeVar("T")


class JobStatusEnum(str, Enum):
    pending = "pending"
    cloning = "cloning"
    parsing = "parsing"
    graphing = "graphing"
    indexing = "indexing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class IngestRequest(BaseModel):
    url: HttpUrl
    branch: str | None = None

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, v: str) -> str:
        return validate_github_url(str(v))

    @field_validator("branch")
    @classmethod
    def validate_branch(cls, v: str | None) -> str | None:
        return validate_branch_name(v)


class RepositoryResponse(BaseModel):
    id: str
    url: str
    name: str
    status: JobStatusEnum
    file_count: int
    entity_count: int
    error_message: str | None = None

    model_config = {"from_attributes": True}


class JobResponse(BaseModel):
    id: str
    repository_id: str
    status: JobStatusEnum
    stage: str
    progress: int
    retry_count: int = 0
    cancelled: bool = False
    error_message: str | None = None

    model_config = {"from_attributes": True}


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    has_more: bool


class StructureNode(BaseModel):
    name: str
    path: str
    type: str
    children: list["StructureNode"] = Field(default_factory=list)


class StructureResponse(BaseModel):
    repository_id: str
    root: StructureNode
    total_files: int
    total_directories: int


class GraphResponse(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    page: int = 1
    page_size: int = 200
    has_more: bool = False


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    repository_id: str

    @field_validator("repository_id")
    @classmethod
    def validate_repo(cls, v: str) -> str:
        return validate_repo_id(v)

    @field_validator("question")
    @classmethod
    def sanitize_question(cls, v: str) -> str:
        return sanitize_user_question(v, settings.max_question_length)


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list)


class DiagramRequest(BaseModel):
    repository_id: str
    diagram_type: str = Field(default="architecture", pattern="^(architecture|module|dependency)$")

    @field_validator("repository_id")
    @classmethod
    def validate_repo(cls, v: str) -> str:
        return validate_repo_id(v)


class DiagramResponse(BaseModel):
    mermaid: str
    description: str


class ReadmeRequest(BaseModel):
    repository_id: str

    @field_validator("repository_id")
    @classmethod
    def validate_repo(cls, v: str) -> str:
        return validate_repo_id(v)


class ReadmeResponse(BaseModel):
    content: str


class ModuleSummaryRequest(BaseModel):
    repository_id: str
    module_path: str | None = Field(default=None, max_length=512)

    @field_validator("repository_id")
    @classmethod
    def validate_repo(cls, v: str) -> str:
        return validate_repo_id(v)


class ModuleSummaryResponse(BaseModel):
    summary: str
    modules: list[dict[str, Any]] = Field(default_factory=list)
