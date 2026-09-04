from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    top_n_cases: int = 20
    llm_max_concurrency: int = 6
    llm_timeout_seconds: int = 45
    llm_max_retries: int = 2

    duckdb_path: str = "data/processed/procurement.duckdb"
    raw_dataset_path: str = "data/raw/nigeria_bpp_full.jsonl"
    investigations_dir: str = "data/processed/investigations"

    @property
    def llm_configured(self) -> bool:
        return bool(self.openrouter_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
