from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from decision_assistant.ingestion.profiles import (
    CHUNKING_PROFILE_PRESETS,
    DEFAULT_CHUNKING_PROFILE_PRESET,
)


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
    generation_provider: str = "gemini"
    embedding_provider: str = "gemini"
    gemini_api_key: SecretStr | None = None
    gemini_generation_model: str = "gemini-3.1-flash-lite"
    gemini_embedding_model: str = "gemini-embedding-2"
    gemini_embedding_dimension: int = 768
    gemini_embedding_config_version: str = "retrieval-prefix-v1"
    gemini_generation_prompt_version: str = "gemini-json-v3"
    gemini_embedding_batch_size: int = 32
    gemini_max_prompt_characters: int = 100_000
    ollama_base_url: str = "http://ollama:11434"
    ollama_generation_model: str = "qwen3:8b"
    ollama_embedding_model: str = "embeddinggemma"
    ollama_embedding_dimension: int = 768
    frontend_origin: str = "http://localhost:5173"
    auth_jwt_secret: SecretStr | None = None
    auth_access_token_ttl_minutes: int = Field(default=24 * 60, gt=0)
    auth_bootstrap_username: str | None = None
    auth_bootstrap_password: SecretStr | None = None
    max_upload_bytes: int = 25 * 1024 * 1024
    model_timeout_seconds: float = 120.0
    model_retry_count: int = 2
    rerank_enabled: bool = False
    rerank_candidate_limit: int = 12
    rerank_min_candidates: int = 6
    rerank_final_limit: int = 5
    chunking_profile_preset: str = DEFAULT_CHUNKING_PROFILE_PRESET
    evaluation_dataset_path: Path = Path("/workspace/evaluation/questions.json")

    @field_validator("chunking_profile_preset")
    @classmethod
    def _validate_chunking_profile_preset(cls, value: str) -> str:
        if value not in CHUNKING_PROFILE_PRESETS:
            raise ValueError(
                f"Unknown chunking profile preset {value!r}; "
                f"expected one of {sorted(CHUNKING_PROFILE_PRESETS)}"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
