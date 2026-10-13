import asyncio
import re
from pathlib import Path
from typing import Iterable

import frontmatter
from sqlalchemy import delete

from app.core.database import get_session_factory
from app.knowledge.embeddings import embed_documents
from app.knowledge.models import KnowledgeChunk

KNOWLEDGE_DIR = Path("knowledge")
CHUNK_SIZE = 900
CHUNK_OVERLAP = 150


def load_documents() -> Iterable[tuple[str, dict, str]]:
    for path in sorted(KNOWLEDGE_DIR.rglob("*.md")):
        post = frontmatter.load(path)
        meta = dict(post.metadata)
        meta["path"] = str(path.relative_to(KNOWLEDGE_DIR))
        yield str(path.relative_to(KNOWLEDGE_DIR)), meta, post.content


def split_into_chunks(
    text: str,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paragraphs:
        if len(buf) + len(p) + 2 <= size:
            buf = f"{buf}\n\n{p}" if buf else p
        else:
            if buf:
                chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)

    if overlap <= 0 or len(chunks) < 2:
        return chunks

    result = [chunks[0]]
    for i in range(1, len(chunks)):
        tail = result[-1][-overlap:]
        result.append((tail + "\n\n" + chunks[i]).strip())
    return result


async def ingest_all(wipe: bool = True) -> None:
    factory = get_session_factory()
    async with factory() as session:
        if wipe:
            await session.execute(delete(KnowledgeChunk))
            await session.commit()

        rows: list[KnowledgeChunk] = []
        for doc_id, meta, text in load_documents():
            chunks = split_into_chunks(text)
            print(f"[ingest] {doc_id}: {len(chunks)} chunks")
            vectors = await embed_documents(chunks)
            for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                rows.append(KnowledgeChunk(
                    doc_id=doc_id,
                    chunk_index=i,
                    content=chunk,
                    meta=meta,
                    embedding=vec,
                ))
        session.add_all(rows)
        await session.commit()
        print(f"[ingest] done: {len(rows)} chunks")


if __name__ == "__main__":
    asyncio.run(ingest_all())
