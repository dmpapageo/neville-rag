"""Retrieval: question -> query embedding -> Pinecone top-K -> rerank -> results.

Run a quick test from the project root:
    PYTHONPATH=backend uv run python -m app.retrieval.search
    PYTHONPATH=backend uv run python -m app.retrieval.search "What does Neville say about sleep?"

Keys come from app.config.settings (env). Nothing hardcoded.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import voyageai
import voyageai.error
from pinecone import Pinecone

from app.config import settings

EMBED_MODEL = "voyage-3.5-lite"       # must match the ingestion embedder
RERANK_MODEL = "rerank-2.5-lite"      # Voyage cross-encoder reranker
TOP_K = 10                            # candidates pulled from Pinecone (vector search)
TOP_N = 4                             # final chunks kept after reranking

_vo = voyageai.Client(api_key=settings.voyage_api_key)
_index = Pinecone(api_key=settings.pinecone_api_key).Index(settings.pinecone_index)


def _with_backoff(fn, *, tries: int = 5, base: float = 2.0):
    """Reactive retry on a 429 with exponential backoff. This is NOT proactive
    pacing — it only sleeps if the API actually rate-limits us (rare on the paid
    tier), so it never adds latency to a normal request."""
    for attempt in range(tries):
        try:
            return fn()
        except voyageai.error.RateLimitError:
            if attempt == tries - 1:
                raise
            wait = base * (2 ** attempt)
            print(f"  [rate limited — retrying in {wait:.0f}s]", file=sys.stderr)
            time.sleep(wait)


@dataclass
class Result:
    rank: int
    rerank_score: float   # cross-encoder relevance (the ranking that decides order)
    vector_score: float   # original cosine similarity from Pinecone
    section: str
    chunk_index: int
    char_start: int
    char_end: int
    text: str


def embed_query(question: str) -> list[float]:
    # input_type="query" — NOT "document". Voyage embeds queries and documents
    # with different instructions so a short question lands near the passages
    # that ANSWER it, rather than near passages that merely resemble it.
    return _with_backoff(
        lambda: _vo.embed([question], model=EMBED_MODEL, input_type="query").embeddings[0]
    )


def retrieve(question: str, *, top_k: int = TOP_K, top_n: int = TOP_N) -> list[Result]:
    qvec = embed_query(question)

    # 1) vector search: fast approximate nearest neighbours by cosine similarity
    matches = _index.query(vector=qvec, top_k=top_k, include_metadata=True).matches
    if not matches:
        return []

    # 2) rerank: a cross-encoder reads (question, chunk) together and scores true
    #    relevance, fixing cases where cosine ranked a lexically-similar but less
    #    relevant chunk too high.
    docs = [m.metadata["text"] for m in matches]
    reranked = _with_backoff(
        lambda: _vo.rerank(question, docs, model=RERANK_MODEL, top_k=top_n)
    )

    results = []
    for rank, r in enumerate(reranked.results, start=1):
        m = matches[r.index]
        md = m.metadata
        results.append(Result(
            rank=rank,
            rerank_score=r.relevance_score,
            vector_score=m.score,
            section=md["section"],
            chunk_index=int(md["chunk_index"]),
            char_start=int(md["char_start"]),
            char_end=int(md["char_end"]),
            text=md["text"],
        ))
    return results


def _print(question: str, results: list[Result]) -> None:
    print("\n" + "=" * 88)
    print(f"Q: {question}")
    print("=" * 88)
    for r in results:
        print(f"\n[{r.rank}] rerank={r.rerank_score:.4f}  vector={r.vector_score:.4f}  "
              f"| {r.section} | chunk #{r.chunk_index} | chars {r.char_start}–{r.char_end}")
        snippet = r.text if len(r.text) <= 320 else r.text[:317] + "..."
        print(f"    {snippet}")


def main() -> None:
    questions = sys.argv[1:] or [
        "What does Neville say about sleep?",
        "How does feeling relate to prayer?",
    ]
    for q in questions:
        _print(q, retrieve(q))


if __name__ == "__main__":
    main()
