import asyncio
import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    print("Connecting to:", url)
    conn = await asyncpg.connect(url)
    row = await conn.fetchrow("SELECT version(), inet_server_addr()")
    print("version:", row["version"])
    print("server_addr:", row["inet_server_addr"])
    await conn.close()


asyncio.run(main())
