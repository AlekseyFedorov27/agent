from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "agent-backend"
    app_env: str = "dev"
    debug: bool = False

    database_url: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7


    openai_api_key: str
    openai_base_url: str = "https://tokenharbor.ai/v1"
    llm_model: str = "deepseek-v4.1-flash:free"
    llm_temperature: float = 0.0
    llm_top_p: float = 1.0

    ollama_base_url: str = "http://localhost:11434" 
    ollama_model: str = "llama3.1:8b"
    ollama_temperature: float = 0.0
    ollama_top_p: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()