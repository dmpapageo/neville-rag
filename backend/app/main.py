"""FastAPI app: serves the demo page and a JSON endpoint over the RAG pipeline.

Run from the project root:
    PYTHONPATH=backend uv run uvicorn app.main:app --port 8000

Keys stay server-side (app.config reads them from env); the browser only talks
to this backend.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.generation.generate import answer as generate_answer
from app.generation.generate import stream_answer

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="Feeling Is the Secret — RAG")


class AskRequest(BaseModel):
    question: str


@app.post("/api/ask")
def ask(req: AskRequest):
    question = req.question.strip()
    if not question:
        return JSONResponse({"error": "Please enter a question."}, status_code=400)
    try:
        a = generate_answer(question)
    except Exception as exc:  # surface backend failures (e.g. rate limits) to the UI
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=502)

    top_score = max((r.rerank_score for r in a.results), default=0.0)
    return {
        "question": a.question,
        "answer": a.text,
        "top_score": top_score,
        "citations": [
            {
                "marker": c.marker,
                "chunk_index": c.chunk_index,
                "section": c.section,
                "cited_text": c.cited_text,
                "char_start": c.source_char_start,
                "char_end": c.source_char_end,
            }
            for c in a.citations
        ],
        "sources": [
            {
                "chunk_index": r.chunk_index,
                "section": r.section,
                "text": r.text,
                "char_start": r.char_start,
                "rerank_score": r.rerank_score,
                "vector_score": r.vector_score,
            }
            for r in a.results
        ],
    }


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@app.post("/api/ask/stream")
def ask_stream(req: AskRequest):
    question = req.question.strip()

    def gen():
        if not question:
            yield _sse({"type": "error", "message": "Please enter a question."})
            return
        try:
            for event in stream_answer(question):
                yield _sse(event)
        except Exception as exc:  # surface backend failures mid-stream
            yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
