from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = (
        "postgresql+asyncpg://decision_assistant:decision_assistant"
        "@db:5432/decision_assistant"
    )
    upload_directory: Path = Path("/workspace/uploads")
    ollama_base_url: str = "http://ollama:11434"
    ollama_generation_model: str = "qwen3:8b"
    ollama_embedding_model: str = "embeddinggemma"
    ollama_embedding_dimension: int = 768
    frontend_origin: str = "http://localhost:5173"
    max_upload_bytes: int = 25 * 1024 * 1024
    model_timeout_seconds: float = 120.0
    model_retry_count: int = 2
    evaluation_dataset_path: Path = Path("/workspace/evaluation/questions.json")


@lru_cache
def get_settings() -> Settings:
    return Settings()
