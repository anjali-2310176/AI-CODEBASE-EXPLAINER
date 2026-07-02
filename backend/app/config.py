from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://explainer:explainer@localhost:5432/codebase_explainer"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "explainer"

    # LLM
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    chat_model: str = "gpt-4o-mini"
    max_chunk_tokens: int = 512
    retrieval_top_k: int = 8

    # Storage
    repos_dir: str = "./data/repos"
    index_dir: str = "./data/indexes"
    metadata_dir: str = "./data/metadata"

    # Resource limits
    max_repo_size_mb: int = 500
    max_file_count: int = 5000
    max_file_size_kb: int = 512
    max_question_length: int = 2000
    max_request_body_mb: int = 1
    clone_depth: int = 1
    delete_clone_after_index: bool = True
    retention_days: int = 30

    # Processing
    parse_batch_size: int = 50
    graph_batch_size: int = 200
    embed_batch_size: int = 100
    parse_workers: int = 4
    job_timeout_seconds: int = 3600
    max_job_retries: int = 3
    retry_backoff_base: float = 2.0

    # API
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    rate_limit_per_minute: int = 60
    default_page_size: int = 20
    max_page_size: int = 100

    # Security
    allowed_git_hosts: str = "github.com,www.github.com"
    block_private_ips: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_hosts(self) -> set[str]:
        return {h.strip().lower() for h in self.allowed_git_hosts.split(",") if h.strip()}

    @property
    def max_repo_size_bytes(self) -> int:
        return self.max_repo_size_mb * 1024 * 1024

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_kb * 1024


settings = Settings()
