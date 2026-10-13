"""Единая точка создания LLM-клиента."""

import logging
from functools import lru_cache

from langchain_openai import ChatOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_llm() -> ChatOpenAI:
    """Создаёт кешированный клиент, не выводя секреты в логи."""
    settings = get_settings()
    logger.info(
        "Инициализация LLM: base_url=%s, model=%s",
        settings.openai_base_url,
        settings.llm_model,
    )
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=settings.llm_temperature,
        top_p=settings.llm_top_p,
    )
