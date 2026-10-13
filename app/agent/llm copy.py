# llm.py
from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import get_settings


@lru_cache(maxsize=1)
def get_llm() -> ChatOpenAI:
    settings = get_settings()
    print(f"[llm] base_url = {settings.openai_base_url}")
    print(f"[llm] model    = {settings.llm_model}")
    print(f"[llm] key[:8]  = {settings.openai_api_key[:8]}...")
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=settings.llm_temperature,
        top_p=settings.llm_top_p,
    )