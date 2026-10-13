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
    interests = request.get("interests") or []

    if not destination and not country:
        raise ValueError("Узел research вызван без destination и country")

    search_location = country or destination
    filters = {"country_ru": country} if country else None
    interests_text = " ".join(str(item) for item in interests if item)
    queries = {
        "attractions": f"{search_location} достопримечательности что посмотреть {interests_text}".strip(),
        "restaurants": f"{search_location} рестораны еда местная кухня бюджет",
        "rules": f"{search_location} виза транспорт правила сезон",
    }

    factory = get_session_factory()
    # Один AsyncSession используется последовательно: AsyncSession нельзя
    # безопасно шарить между конкурентными запросами.
    try:
        async with factory() as session:
            results: dict[str, list[dict[str, Any]]] = {}
            for category, query in queries.items():
                documents = await search_knowledge(
                    session, query, top_k=5, filters=filters,
                )
                # Убираем дубликаты и сохраняем метаданные/оценку для трассировки.
                unique: list[dict[str, Any]] = []
                seen: set[str] = set()
                for document in documents:
                    doc_id = str(document.get("doc_id") or "")
                    if doc_id and doc_id in seen:
                        continue
                    if doc_id:
                        seen.add(doc_id)
                    unique.append(document)
                results[category] = unique
    except Exception as exc:
        logger.exception("RAG-поиск не выполнен для направления %r", search_location)
        raise RuntimeError(
            f"Не удалось выполнить поиск по базе знаний для направления {search_location!r}"
        ) from exc

    logger.info(
        "RAG завершён для %r: attractions=%d, restaurants=%d, rules=%d",
        search_location,
        len(results["attractions"]),
        len(results["restaurants"]),
        len(results["rules"]),
    )
    return {"research": results}
