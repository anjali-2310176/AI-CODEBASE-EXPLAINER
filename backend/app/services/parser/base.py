from abc import ABC, abstractmethod
from pathlib import Path

from app.services.entities import CodeEntity, CodeRelation, EntityType


class CodeParser(ABC):
    """Abstract parser interface for multi-language support."""

    @property
    @abstractmethod
    def language(self) -> str:
        ...

    @abstractmethod
    def parse_file(self, file_path: Path, repo_path: Path, repository_id: str) -> tuple[list[CodeEntity], list[CodeRelation]]:
        ...

    def supported_extensions(self) -> list[str]:
        return [f".{self.language}"]


class ParserRegistry:
    """Registry for language parsers — add new parsers here for multi-language support."""

    def __init__(self) -> None:
        self._parsers: dict[str, CodeParser] = {}

    def register(self, parser: CodeParser) -> None:
        self._parsers[parser.language] = parser

    def get(self, language: str) -> CodeParser:
        if language not in self._parsers:
            raise ValueError(f"No parser registered for language: {language}")
        return self._parsers[language]

    def get_for_file(self, file_path: Path) -> CodeParser | None:
        ext_map = {ext: lang for lang, p in self._parsers.items() for ext in p.supported_extensions()}
        parser = ext_map.get(file_path.suffix)
        return self._parsers.get(parser) if parser else None


parser_registry = ParserRegistry()
