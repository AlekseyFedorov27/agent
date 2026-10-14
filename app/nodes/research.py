"""RAG-исследование направления через базу знаний."""

import logging
from typing import Any

from app.agent.state import AgentState
from app.core.database import get_session_factory
from app.knowledge.retriever import search_knowledge

logger = logging.getLogger(__name__)


async def research(state: AgentState) -> dict[str, Any]:
    request = state.get("request") or {}
    destination = (request.get("destination") or "").strip()
    country = (request.get("country") or "").strip()
    if not destination and not country:
        raise ValueError("Узел research вызван без destination и country")

    location = country or destination
    filters = {"country_ru": country} if country else None
    interests = " ".join(str(i) for i in request.get("interests") or [] if i)

    queries = {
        "attractions": f"{location} достопримечательности что посмотреть {interests}".strip(),
        "restaurants": f"{location} рестораны еда местная кухня бюджет",
        "rules": f"{location} виза транспорт правила сезон",
    }

    results: dict[str, list[dict[str, Any]]] = {}
    try:
        # Один AsyncSession используется последовательно: его нельзя
        # безопасно шарить между конкурентными запросами.
        async with get_session_factory()() as session:
            for category, query in queries.items():
                documents = await search_knowledge(session, query, top_k=5, filters=filters)
                seen: set[str] = set()
                unique = []
                for doc in documents:
                    doc_id = str(doc.get("doc_id") or "")
                    if doc_id and doc_id in seen:
                        continue
                    seen.add(doc_id)
                    unique.append(doc)
                results[category] = unique
    except Exception as exc:
        logger.exception("RAG-поиск не выполнен для направления %r", location)
        raise RuntimeError(
            f"Не удалось выполнить поиск по базе знаний для направления {location!r}"
        ) from exc

    logger.info("RAG завершён для %r: %s", location, {k: len(v) for k, v in results.items()})
    return {"research": results}