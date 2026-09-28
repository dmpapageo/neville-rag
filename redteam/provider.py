"""Promptfoo Python provider: runs the real RAG pipeline (retrieve -> Claude with
citations) for one red-team prompt.

If the test sets vars.context, that text is spliced into the retrieved passages
at rank 1, as if a poisoned chunk had been indexed. App code is untouched: only
the module-level `retrieve` that answer() calls is wrapped for this one call.

Promptfoo calls call_api(prompt, options, context); run it from the repo root.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

INJECTED_SECTION = "Appendix: Notes on Practice"
INJECTED_CHUNK_INDEX = -1


def _poisoned_retrieve(original, text: str):
    from app.retrieval.search import Result

    def retrieve(question, **kw):
        real = original(question, **kw)
        top = max((r.rerank_score for r in real), default=1.0)
        fake = Result(rank=1, rerank_score=top, vector_score=top, section=INJECTED_SECTION,
                      chunk_index=INJECTED_CHUNK_INDEX, char_start=0, char_end=len(text), text=text)
        for r in real:
            r.rank += 1
        return [fake] + real

    return retrieve


def call_api(prompt, options, context):
    from app.generation import generate as gen

    injected = ((context or {}).get("vars") or {}).get("context")
    original = gen.retrieve
    if injected:
        gen.retrieve = _poisoned_retrieve(original, injected)
    try:
        a = gen.answer(prompt)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        gen.retrieve = original

    tin, tout = a.usage.get("input_tokens", 0), a.usage.get("output_tokens", 0)
    return {
        "output": a.text,
        "tokenUsage": {"prompt": tin, "completion": tout, "total": tin + tout},
        "metadata": {
            "injected": bool(injected),
            "retrieved_chunks": [r.chunk_index for r in a.results],
            "cited_chunks": sorted({c.chunk_index for c in a.citations}),
            "top_score": max((r.rerank_score for r in a.results), default=0.0),
            "timings_ms": a.timings_ms,
        },
    }
