"""Embed chunks with Voyage and upsert them into Pinecone.

Run from the project root:  PYTHONPATH=backend uv run python -m app.ingestion.embed

Keys come from the environment via app.config.settings — nothing is hardcoded.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import voyageai
import voyageai.error
from pinecone import Pinecone, ServerlessSpec

from app.config import settings

CHUNKS = Path("data/chunks.jsonl")
EMBED_MODEL = "voyage-3.5-lite"
METRIC = "cosine"                       # see note in the report
CLOUD, REGION = "aws", "us-east-1"      # Pinecone free Starter tier


def load_chunks() -> list[dict]:
    return [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]


def embed(texts: list[str], batch_size: int = 128) -> list[list[float]]:
    """Embed with input_type='document'. Sends large batches (the paid tier
    handles this book in a single request); retries on a 429 with exponential
    backoff. No proactive pacing."""
    vo = voyageai.Client(api_key=settings.voyage_api_key)
    out: list[list[float]] = []
    batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
    for bi, batch in enumerate(batches):
        for attempt in range(5):
            try:
                out.extend(vo.embed(batch, model=EMBED_MODEL, input_type="document").embeddings)
                break
            except voyageai.error.RateLimitError:
                if attempt == 4:
                    raise
                wait = 2.0 * (2 ** attempt)
                print(f"  [rate limited — retrying in {wait:.0f}s]")
                time.sleep(wait)
        print(f"  embedded batch {bi + 1}/{len(batches)} ({len(out)}/{len(texts)})")
    return out


def ensure_index(pc: Pinecone, name: str, dimension: int) -> None:
    if pc.has_index(name):
        print(f"index '{name}' already exists — reusing")
        return
    print(f"creating index '{name}' (dim={dimension}, metric={METRIC}, {CLOUD}/{REGION})")
    pc.create_index(
        name=name,
        dimension=dimension,
        metric=METRIC,
        spec=ServerlessSpec(cloud=CLOUD, region=REGION),
    )
    while not pc.describe_index(name).status["ready"]:
        time.sleep(1)


def main() -> None:
    chunks = load_chunks()
    print(f"loaded {len(chunks)} chunks from {CHUNKS}")

    vectors_raw = embed([c["text"] for c in chunks])
    dim = len(vectors_raw[0])
    print(f"embedded with {EMBED_MODEL}: dimension = {dim}")

    pc = Pinecone(api_key=settings.pinecone_api_key)
    ensure_index(pc, settings.pinecone_index, dim)
    index = pc.Index(settings.pinecone_index)

    vectors = [
        {
            "id": f"chunk-{c['index']}",
            "values": vec,
            "metadata": {
                "chunk_index": c["index"],
                "section": c["section"],
                "text": c["text"],          # stored so retrieval can display the passage
                "char_start": c["char_start"],
                "char_end": c["char_end"],
                "source": c["source"],
            },
        }
        for c, vec in zip(chunks, vectors_raw)
    ]
    index.upsert(vectors=vectors)
    print(f"upserted {len(vectors)} vectors")

    # stats are eventually consistent — poll until the count settles
    target = len(vectors)
    count = 0
    for _ in range(30):
        count = index.describe_index_stats().get("total_vector_count", 0)
        if count >= target:
            break
        time.sleep(1)
    print(f"index vector count: {count} (expected {target})")

    # sanity check: fetch one vector back and confirm its metadata survived
    fetched = index.fetch(ids=["chunk-12"])
    v = fetched.vectors["chunk-12"]
    md = v.metadata
    print("\nsanity fetch — chunk-12:")
    print(f"  values length: {len(v.values)}")
    print(f"  section:       {md['section']}")
    print(f"  chunk_index:   {md['chunk_index']}")
    print(f"  char span:     {md['char_start']}–{md['char_end']}")
    print(f"  text[:90]:     {md['text'][:90]!r}")


if __name__ == "__main__":
    main()
