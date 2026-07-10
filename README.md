# RAG Web App — "Feeling Is the Secret"

A Retrieval-Augmented Generation web app that answers questions about the
public-domain book *Feeling Is the Secret* by Neville Goddard (1944), returning
grounded answers **with citations to the source passages**.

Portfolio + learning project. Built in stages.

## Architecture (target)

- **Ingestion** — load the book text → chunk → embed → store vectors in Pinecone
- **Retrieval** — embed the user question → find relevant chunks → rerank
- **Generation** — feed retrieved chunks to Claude → grounded answer + citations
- **Web UI** — question in; grounded answer + source chunks out
- **Evaluation** — retrieval relevance + answer faithfulness

## Stack

| Layer        | Choice                          | Why |
|--------------|---------------------------------|-----|
| Backend      | Python + FastAPI                | Async API, typed, portfolio-standard |
| LLM          | Claude (Anthropic SDK)          | Grounded generation with native citations |
| Embeddings   | Voyage AI                       | Anthropic's recommended provider; generous free tier |
| Vector store | Pinecone (serverless)           | Managed, free Starter tier |
| Package mgmt | uv                              | Fast, reproducible, no global pip |
| Frontend     | TBD (Stage: UI)                 | Lightweight — see that stage |

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
cp .env.example .env   # then fill in your keys
uv sync                # once dependencies are added
```

Keys are read from environment variables only — never hardcoded.

## Status

- **Stage 1 — Scope & setup** ✅ repo structure, stack decisions, env scaffold
- Ingestion — not started
- Retrieval — not started
- Generation — not started
- UI — not started
- Evaluation — not started
