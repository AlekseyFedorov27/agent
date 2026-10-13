from typing import Any
import logging
from app.agent.state import AgentState
from app.core.database import get_session_factory
from app.knowledge.retriever import search_knowledge


logger = logging.getLogger(__name__)

async def research(state: AgentState) -> dict[str, Any]:
    request = state.get("request") or {}
    # Фильтруем по country, а не по destination
    country = (request.get("country") or request.get("destination") or "").strip()
    interests = request.get("interests") or []

    if not country:
        logger.info("[research] country пустой — возвращаю пустые результаты")
        return {
            "research": {"attractions": [], "restaurants": [], "rules": []},
        }

    country_filter = {"country_ru": country}
    interests_str = " ".join(interests) if interests else ""

    factory = get_session_factory()
    async with factory() as session:
        attractions = await search_knowledge(
            session,
            f"{country} достопримечательности что посмотреть {interests_str}".strip(),
            top_k=5,
            filters=country_filter,
        )
        restaurants = await search_knowledge(
            session,
            f"{country} рестораны еда кухня бюджет",
            top_k=5,
            filters=country_filter,
        )
        rules = await search_knowledge(
            session,
            f"{country} виза транспорт правила погода сезон",
            top_k=5,
            filters=country_filter,
        )

    return {
        "research": {
            "attractions": attractions,
            "restaurants": restaurants,
            "rules": rules,
        }
    }