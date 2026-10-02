# CLAUDE.md

## What this is

A RAG Q&A web app over one public-domain book, *Feeling Is the Secret* (Neville Goddard, 1944). A question is embedded, matched against book chunks in Pinecone, reranked, and answered by Claude using only the retrieved passages, with inline citations that map back to exact character spans in the source text. Refuses out-of-scope questions instead of answering from general knowledge. Single-author portfolio/demo project; no multi-tenancy, no auth.

## Stack

- Python >= 3.12 (`.python-version`: 3.12), package manager `uv` (`uv.lock` committed, no `pip`/`requirements.txt`).
- Backend: FastAPI + uvicorn[standard]; config via pydantic-settings.
- Frontend: one hand-written `frontend/index.html` (342 lines, plain HTML/CSS/JS). No Node, no package.json, no build step.
- LLM: Anthropic SDK. Answerer `claude-opus-4-8` (`backend/app/generation/generate.py`), eval judge `claude-sonnet-5` (`eval/run_eval.py`).
- Embeddings + rerank: Voyage AI, `voyage-3.5-lite` (document/query asymmetric) and `rerank-2.5-lite`.
- Vector store: Pinecone serverless, cosine, aws/us-east-1; top-10 from vector search, top-4 after rerank.

## Commands

There is no scripts section (pyproject has no scripts/entry points); these are the commands documented in the source files, all run from the repo root:

- Install: `uv sync --frozen`
- Dev server: `PYTHONPATH=backend uv run uvicorn app.main:app --port 8000` (then http://127.0.0.1:8000)
- Chunk (writes `data/chunks.jsonl`): `PYTHONPATH=backend uv run python -m app.ingestion.chunk`
- Embed + upsert to Pinecone: `PYTHONPATH=backend uv run python -m app.ingestion.embed`
- Offline tests: `PYTHONPATH=backend uv run --with pytest pytest tests/ -q`
- Live eval (spends API credit, exits 1 on gate breach): `PYTHONPATH=backend uv run python eval/run_eval.py`
- Build/lint/typecheck: none exist. No ruff/mypy/black config in the repo.

## Layout & gotchas

- `backend/app/`: `main.py` (FastAPI: `POST /api/ask`, `POST /api/ask/stream` SSE, `GET /` serves the frontend), `ingestion/{chunk,embed}.py`, `retrieval/search.py`, `generation/generate.py`. `config.py` holds all keys.
- `data/`: committed source `.pdf`, extracted `.txt`, and `chunks.jsonl` (30 chunks). `eval/`: questions, runner, committed `results.json`/`report.md`. Tests: `tests/test_chunking.py` and `tests/test_refusal.py`, both offline.
- **`PYTHONPATH=backend` is required on every command**: `backend` is not a package root on its own and imports are `app.*`.
- **Always run from the repo root**: `chunk.py`/`embed.py` use relative paths (`data/...`).
- `pytest` is not a declared dependency: it is pulled in ad hoc via `uv run --with pytest`.
- Env vars (names only, values in `.env`, never commit): `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `PINECONE_API_KEY`, and optional `PINECONE_INDEX` (defaults to `feeling-is-the-secret`). `Settings()` is instantiated at import time, so importing `app.config` fails without them.
- The Pinecone index must already be populated (`app.ingestion.embed`) before the server or the eval returns anything.
- Folder name `rag-web-app` differs from the git remote repo name `neville-rag` (github.com/dmpapageo/neville-rag). `pyproject.toml` name is `rag-web-app`.
- CI (`.github/workflows/tests.yml`) runs only the offline tests on push/PR; the live eval is local-only by design (it costs API credit).
- The frontend only calls `/api/ask/stream`; the non-streaming `/api/ask` is unused by the UI.
- No PDF extraction script is in the repo. `data/feeling_is_the_secret.txt` is committed as-is and is the input to chunking.
- The answerer is pinned to `claude-opus-4-8`, the last model to pass every eval gate (`eval/report.md`). Opus 5.5 failed citation precision at 87.0% on 2 Oct 2026 (`eval/report-opus-5-5.md`). Rerun `eval/run_eval.py` before changing `MODEL` (costs API credit).
