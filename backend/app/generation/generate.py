"""Grounded generation: question -> retrieve -> Claude answers ONLY from the
retrieved passages, with claim-level citations back to the source.

Run from the project root:
    PYTHONPATH=backend uv run python -m app.generation.generate
    PYTHONPATH=backend uv run python -m app.generation.generate "What does Neville say about sleep?"

Keys come from app.config.settings (env). Nothing hardcoded.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

from anthropic import Anthropic

from app.config import settings
from app.retrieval.search import TOP_K, TOP_N, Result, retrieve

MODEL = "claude-opus-4-8"
MAX_TOKENS = 2048

# Grounding is enforced two ways: (1) the ONLY context Claude receives is the
# retrieved passages (passed as citable `document` blocks), and (2) this system
# prompt forbids outside knowledge and tells it to decline when the passages
# don't answer the question.
SYSTEM = """You are a knowledgeable guide helping readers understand the book \
"Feeling Is the Secret" by Neville Goddard (1944). Answer questions using ONLY the \
provided source passages.

How to answer:
- Explain the ideas in your own clear, accessible, modern language. Paraphrase and \
synthesize what the passages say rather than parroting them — convey the underlying \
idea, not the dated 1940s phrasing.
- Use direct quotes sparingly: only a short, striking phrase when the exact wording \
genuinely adds value. Do not quote whole sentences or passages verbatim by default.
- Prioritize clarity and readability. Be reasonably concise but not terse — enough to \
explain the idea well.

Grounding (non-negotiable):
- Use ONLY what the provided passages support. Do not add outside knowledge or general \
facts about the book or its author.
- Ground every claim in the passages and cite the supporting source.
- If the passages do not contain enough to answer, say plainly that the book (as \
provided) does not address the question. Do not guess or fill gaps from general knowledge.
- Give the answer directly; do not narrate your reasoning."""

_client = Anthropic(api_key=settings.anthropic_api_key)


@dataclass
class Citation:
    marker: int          # [n] shown inline in the answer
    section: str
    chunk_index: int
    source_char_start: int   # absolute offset into feeling_is_the_secret.txt
    source_char_end: int
    cited_text: str


@dataclass
class Answer:
    question: str
    text: str                 # answer with inline [n] citation markers
    citations: list[Citation]
    results: list[Result]     # what retrieval fed the model (for transparency)
    timings_ms: dict = field(default_factory=dict)  # retrieval / generation wall time
    usage: dict = field(default_factory=dict)       # input_tokens / output_tokens


def _documents(results: list[Result]) -> list[dict]:
    # Each retrieved chunk becomes a citable plain-text document. Citation char
    # offsets come back relative to each document's own text, so we can map them
    # to absolute offsets in the source file via the chunk's char_start.
    return [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": r.text},
            "title": f"{r.section} (chunk {r.chunk_index})",
            "citations": {"enabled": True},
        }
        for r in results
    ]


def answer(question: str, *, top_k: int = TOP_K, top_n: int = TOP_N) -> Answer:
    t0 = time.perf_counter()
    results = retrieve(question, top_k=top_k, top_n=top_n)
    t1 = time.perf_counter()
    if not results:
        return Answer(question, "No passages were retrieved for this question.", [], [],
                      timings_ms={"retrieval": round((t1 - t0) * 1000)})

    content = _documents(results) + [{"type": "text", "text": f"Question: {question}"}]
    resp = _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        # Thinking is disabled to keep this grounded-extraction task fast.
        thinking={"type": "disabled"},
        system=SYSTEM,
        messages=[{"role": "user", "content": content}],
    )
    t2 = time.perf_counter()

    text_out, citations = "", []
    for block in resp.content:
        if block.type != "text":
            continue
        text_out += block.text
        for c in getattr(block, "citations", None) or []:
            r = results[c.document_index]
            citations.append(Citation(
                marker=len(citations) + 1,
                section=r.section,
                chunk_index=r.chunk_index,
                source_char_start=r.char_start + c.start_char_index,
                source_char_end=r.char_start + c.end_char_index,
                cited_text=c.cited_text,
            ))
        if getattr(block, "citations", None):
            markers = range(len(citations) - len(block.citations) + 1, len(citations) + 1)
            text_out += " " + "".join(f"[{m}]" for m in markers)

    if resp.stop_reason == "max_tokens":
        text_out += "\n\n[note: answer hit the max_tokens cap and may be truncated]"

    return Answer(
        question, text_out, citations, results,
        timings_ms={"retrieval": round((t1 - t0) * 1000), "generation": round((t2 - t1) * 1000)},
        usage={"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens},
    )


def stream_answer(question: str, *, top_k: int = TOP_K, top_n: int = TOP_N):
    """Generator yielding SSE-friendly dict events for progressive rendering:
    one 'meta' (sources + top_score), then interleaved 'text'/'citation' deltas
    as Claude streams, then 'done'. Same grounding + citation mapping as answer(),
    just incremental. Citation char offsets are converted to absolute source
    offsets (chunk.char_start + delta offset), matching answer()."""
    results = retrieve(question, top_k=top_k, top_n=top_n)
    top_score = max((r.rerank_score for r in results), default=0.0)
    yield {
        "type": "meta",
        "top_score": top_score,
        "sources": [
            {"chunk_index": r.chunk_index, "section": r.section, "text": r.text,
             "char_start": r.char_start, "rerank_score": r.rerank_score,
             "vector_score": r.vector_score}
            for r in results
        ],
    }
    if not results:
        yield {"type": "done"}
        return

    content = _documents(results) + [{"type": "text", "text": f"Question: {question}"}]
    marker = 0
    with _client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "disabled"},
        system=SYSTEM,
        messages=[{"role": "user", "content": content}],
    ) as stream:
        for event in stream:
            if event.type != "content_block_delta":
                continue
            d = event.delta
            if d.type == "text_delta":
                yield {"type": "text", "text": d.text}
            elif d.type == "citations_delta":
                c = d.citation
                marker += 1
                r = results[c.document_index]
                yield {
                    "type": "citation",
                    "marker": marker,
                    "chunk_index": r.chunk_index,
                    "section": r.section,
                    "cited_text": c.cited_text,
                    "char_start": r.char_start + c.start_char_index,
                    "char_end": r.char_start + c.end_char_index,
                }
        final = stream.get_final_message()
    if final.stop_reason == "max_tokens":
        yield {"type": "text", "text": "\n\n[note: answer hit the max_tokens cap and may be truncated]"}
    yield {"type": "done"}


def _print(a: Answer) -> None:
    print("\n" + "=" * 88)
    print(f"Q: {a.question}")
    print("-" * 88)
    print(a.text.strip())
    if a.citations:
        print("\nSources:")
        for c in a.citations:
            snip = c.cited_text if len(c.cited_text) <= 140 else c.cited_text[:137] + "..."
            print(f"  [{c.marker}] {c.section} | chunk #{c.chunk_index} | "
                  f"src chars {c.source_char_start}-{c.source_char_end}")
            print(f"      “{snip}”")
    else:
        print("\n(no citations — answer not grounded in a specific passage)")
    # show what retrieval surfaced, so low relevance is visible on 'not covered' cases
    print("\nRetrieved (top rerank scores): " +
          ", ".join(f"#{r.chunk_index}={r.rerank_score:.3f}" for r in a.results))


def main() -> None:
    questions = sys.argv[1:] or [
        "What does Neville say about sleep?",
        "How does feeling relate to prayer?",
        "What does the book say about diet and exercise?",  # not covered -> should decline
    ]
    for q in questions:
        _print(answer(q))


if __name__ == "__main__":
    main()
