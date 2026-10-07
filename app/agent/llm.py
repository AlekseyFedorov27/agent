from functools import lru_cache

from langchain_ollama import ChatOllama

from app.config import get_settings


@lru_cache(maxsize=1)
def get_llm() -> ChatOllama:
    settings = get_settings()
    return ChatOllama(
        model=settings.ollama_model,
        temperature=settings.ollama_temperature,
        top_p=settings.ollama_top_p,
        base_url=settings.ollama_base_url,
    )