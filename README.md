# Feeling Is the Secret: RAG Q&A

A retrieval-augmented generation (RAG) web app that answers questions about Neville Goddard's 1944 public-domain book *Feeling Is the Secret*, grounded strictly in the source text with inline citations.

Ask a question, and the app retrieves the most relevant passages from the book, generates an answer based only on those passages, and cites each claim back to its exact source. If the book doesn't cover a topic, the app says so rather than inventing an answer.

## Demo
https://github.com/user-attachments/assets/caca88da-b1b2-4d26-9dfa-a33e4dc7eac4

## What it does

- **Grounded answers only.** Responses are built strictly from retrieved passages of the book, not the model's general knowledge.
- **Inline citations.** Each answer includes citation markers; clicking one highlights the exact source passage it came from.
- **Honest refusals.** Ask about something outside the book (e.g. diet and exercise) and the app tells you the book doesn't cover it, instead of fabricating.
- **Streaming responses.** Answers stream in progressively rather than appearing after a blank wait.

## How it works

The pipeline has four stages:

1. **Ingestion.** The book is extracted from PDF to clean text (layout-aware, preserving the author's terms), split with hybrid section-aware chunking (paragraph boundaries, capped at ~300-400 tokens with ~15% overlap), embedded with Voyage AI, and stored in Pinecone.
2. **Retrieval.** A question is embedded (using query-type embeddings), matched against the stored chunks via cosine similarity in Pinecone, then reranked for precision.
3. **Grounded generation.** The top passages plus the question are sent to Claude, which answers using only the provided text and cites its sources. Context isolation (the model only sees retrieved passages) plus a strict system prompt enforce grounding.
4. **Web UI.** A lightweight frontend shows the streamed answer, its citations, and the source passages, with click-to-highlight linking each citation to its exact span in the text.

## Stack

- **Generation:** Claude (Anthropic API)
- **Embeddings:** Voyage AI (`voyage-3.5-lite`)
- **Vector store:** Pinecone (serverless, cosine, 1024-dim)
- **Reranking:** Voyage reranker
- **Backend:** FastAPI
- **Frontend:** plain HTML/CSS/JS (no build step)

## Running it locally

Requires API keys for Anthropic, Voyage, and Pinecone.

1. Copy `.env.example` to `.env` and add your keys.
2. Install dependencies with `uv`.
3. Ingest the book (one time): run the ingestion step to chunk, embed, and upsert to Pinecone.
4. Start the server:
   ```
   PYTHONPATH=backend uv run uvicorn app.main:app --port 8000
   ```
5. Open `http://127.0.0.1:8000` and ask a question.

## Design notes

- **Why a separate embeddings provider?** Claude generates text but doesn't produce embeddings, so retrieval uses a dedicated embeddings model (Voyage, Anthropic's recommended provider). Embeddings measure similarity for retrieval; generation writes the answer.
- **Why reranking?** Raw vector similarity casts a wide net; a reranker re-scores the top candidates for relevance, improving which passages actually reach the model.
- **Grounding discipline.** The model is given only the retrieved passages and is instructed to answer solely from them, cite every claim, and refuse when the passages don't support an answer.

## Note on the source text

*Feeling Is the Secret* (Neville Goddard, 1944) is in the public domain. This project uses the original text for retrieval and displays passages for citation purposes.
