import asyncio
import asyncpg


async def main() -> None:
    conn = await asyncpg.connect(
        "postgresql://postgres:postgres@localhost:5432/agent_db"
    )

    ext = await conn.fetch(
        "SELECT extname FROM pg_extension WHERE extname = 'vector'"
    )
    print("vector extension:", bool(ext))

    cols = await conn.fetch(
        """
        SELECT column_name, udt_name
        FROM information_schema.columns
        WHERE table_name = 'knowledge_chunks'
        ORDER BY ordinal_position
        """
    )
    print("columns:")
    for c in cols:
        print("  -", c["column_name"], c["udt_name"])

    idx = await conn.fetch(
        "SELECT indexname FROM pg_indexes WHERE tablename = 'knowledge_chunks'"
    )
    print("indexes:", [r["indexname"] for r in idx])

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
