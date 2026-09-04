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

1. **Ingestion.** The book is extracted from PDF to clean text (layout-aware, preserving the author's terms), split with hybrid section-aware chunking (paragraph boundaries, capped at 350 tokens with 15% overlap, sized with Voyage's own tokenizer — 30 chunks for this book), embedded with Voyage AI, and stored in Pinecone.
2. **Retrieval.** A question is embedded (using query-type embeddings), matched against the stored chunks via cosine similarity in Pinecone, then reranked for precision.
3. **Grounded generation.** The top passages plus the question are sent to Claude, which answers using only the provided text and cites its sources. Context isolation (the model only sees retrieved passages) plus a strict system prompt enforce grounding.
4. **Web UI.** A lightweight frontend shows the streamed answer, its citations, and the source passages, with click-to-highlight linking each citation to its exact span in the text.

## Stack

- **Generation:** Claude (`claude-opus-5`, Anthropic API, native citations)
- **Embeddings:** Voyage AI (`voyage-3.5-lite`, query/document asymmetric)
- **Vector store:** Pinecone (serverless, cosine; top-10 candidates)
- **Reranking:** Voyage `rerank-2.5-lite` cross-encoder (top-4 kept)
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

## Evaluation

Two layers, same idea as my [LLM eval harness](https://github.com/dmpapageo/llm-eval-harness): deterministic checks where possible, an LLM judge only for what can't be checked mechanically.

**Offline tests** (`tests/`, run on every push in GitHub Actions, no keys): the chunker respects the token cap, overlaps inside a section, never crosses a section boundary, and — the property citation highlighting depends on — every chunk's `char_start`/`char_end` indexes back to its own text in the source file, for both synthetic input and the committed `data/chunks.jsonl`. It also checks that every gold phrase in the eval set really exists in the book.

```
PYTHONPATH=backend uv run --with pytest pytest tests/ -q
```

**Live eval** (`eval/run_eval.py`, run locally — it spends API credit): 20 hand-labelled questions in `eval/questions.json`, 16 answerable and 4 deliberately out of scope. Each answerable question carries *gold phrases* — exact sentences from the book that answer it — so grading needs no opinion about which chunk is "right":

| Metric | How it's graded |
|---|---|
| Refusal accuracy | deterministic — refused exactly the out-of-scope questions |
| Citation precision | deterministic — share of citations whose source span lands in a chunk containing a gold phrase |
| Gold recall | deterministic — answerable questions with at least one grounded citation |
| Faithfulness | LLM-as-judge (`claude-sonnet-5`, a different family than the answerer) — every claim supported by the retrieved passages, 1–5, with unsupported claims listed |
| Coverage | deterministic, advisory — `must_mention` terms present |
| Latency / tokens | measured — retrieval vs generation wall time, tokens per answer |

Gates: refusal accuracy 100%, citation precision ≥ 90%, gold recall ≥ 90%, mean faithfulness ≥ 4.5, per-case faithfulness ≥ 4. The script exits 1 on any breach and writes `eval/results.json` and `eval/report.md`.

```
PYTHONPATH=backend uv run python eval/run_eval.py
```

**Latest results** (`eval/report.md`, Opus 4.8 answering, Sonnet 5 judging): refusal accuracy 100% (4/4 out-of-scope questions declined, 16/16 in-scope answered), citation precision 97.0% (96/99 citations land in a gold chunk), gold recall 100%, mean faithfulness 4.94 with no case below 4. Retrieval p50 1.6 s (embed + Pinecone + rerank), generation p50 8.1 s; ≈3.9k input / 560 output tokens per answer.

Two things the first run taught me, kept here on purpose:

- **The labels were the bug, not the app.** The first run scored citation precision at 76.8%. Reading every "ungrounded" citation against the book showed all of them were legitimate — the model had cited *additional* passages that answered the question, and my gold set only listed the one sentence I'd had in mind. Gold phrases were widened only where the passage genuinely answers the question; chunk-level precision is a lower bound that is only as good as label coverage, and it should be read next to the judge's faithfulness score, which measures grounding directly.
- **The judge catches premise-parroting.** The one remaining sub-5 case asks about "the final chapter"; the passages say "Chapter 4" but never that it is the last one, and the answer repeated the question's framing. The judge marked that unsupported. That is the correct call, so the question stays as written.

## Design notes

- **Why a separate embeddings provider?** Claude generates text but doesn't produce embeddings, so retrieval uses a dedicated embeddings model (Voyage, Anthropic's recommended provider). Embeddings measure similarity for retrieval; generation writes the answer.
- **Why reranking?** Raw vector similarity casts a wide net; a reranker re-scores the top candidates for relevance, improving which passages actually reach the model.
- **Grounding discipline.** The model is given only the retrieved passages and is instructed to answer solely from them, cite every claim, and refuse when the passages don't support an answer.

## Note on the source text

*Feeling Is the Secret* (Neville Goddard, 1944) is in the public domain. This project uses the original text for retrieval and displays passages for citation purposes.
