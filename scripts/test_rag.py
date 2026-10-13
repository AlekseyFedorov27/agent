import asyncio

from app.core.database import get_session_factory
from app.knowledge.retriever import search_knowledge


async def main() -> None:
    factory = get_session_factory()
    async with factory() as session:
        queries = [
            ("Париж архитектура музей",           {"country_ru": "Франция"}),
            ("Барселона Гауди Саграда",           {"country_ru": "Испания"}),
            ("виза чаевые транспорт Испания",     {"country_ru": "Испания"}),
            ("недорого поесть Рим паста",         {"country_ru": "Италия"}),
            ("сёрф Лиссабон океан",               {"country_ru": "Португалия"}),
            ("бюджетное жильё hostel",            None),
        ]
        for query, filters in queries:
            print(f"\n=== {query!r} | filters={filters} ===")
            results = await search_knowledge(
                session, query, top_k=3, filters=filters,
            )
            if not results:
                print("  (пусто)")
                continue
            for r in results:
                print(f"  {r['score']:.3f}  {r['doc_id']}")
                preview = r["content"][:120].replace("\n", " ")
                print(f"         {preview}...")
                print(f"         chunk_index = {r['meta'].get('path')}")


if __name__ == "__main__":
    asyncio.run(main())