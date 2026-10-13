from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.embeddings import embed_query
from app.knowledge.models import KnowledgeChunk


async def search_knowledge(
    session: AsyncSession,
    query: str,
    *,
    top_k: int = 5,
    filters: dict[str, Any] | None = None,
) -> list[dict]:
    vec = await embed_query(query)

    stmt = select(
        KnowledgeChunk,
        KnowledgeChunk.embedding.cosine_distance(vec).label("distance"),
    ).order_by("distance").limit(top_k)

    if filters:
        for key, value in filters.items():
            stmt = stmt.where(KnowledgeChunk.meta[key].astext == str(value))

    result = await session.execute(stmt)
    return [
        {
            "doc_id": row.KnowledgeChunk.doc_id,
            "content": row.KnowledgeChunk.content,
            "meta": row.KnowledgeChunk.meta,
            "score": 1.0 - float(row.distance),
        }
        for row in result
    ]
