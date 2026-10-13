from functools import lru_cache

from langchain_ollama import OllamaEmbeddings

from app.config import get_settings

EMBED_DIM = 768  # nomic-embed-text возвращает ровно 768


@lru_cache(maxsize=1)
def get_embeddings() -> OllamaEmbeddings:
    settings = get_settings()
    return OllamaEmbeddings(
        model="nomic-embed-text",
        base_url=settings.ollama_base_url,
        dimensions=768,
    )


async def embed_query(text: str) -> list[float]:
    return await get_embeddings().aembed_query(text)


async def embed_documents(texts: list[str]) -> list[list[float]]:
    return await get_embeddings().aembed_documents(texts)