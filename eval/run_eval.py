"""End-to-end eval for the RAG app: asks every question in eval/questions.json
through the real pipeline (retrieve -> Claude with citations) and grades:

  refusal accuracy      deterministic  did it refuse exactly the out-of-scope questions?
  citation precision    deterministic  share of citations whose source span lands in a
                                       chunk that contains a gold phrase for that question
  gold recall           deterministic  share of answerable questions with >=1 grounded citation
  coverage (advisory)   deterministic  must_mention terms present in the answer
  faithfulness          LLM-as-judge   Sonnet grades whether every claim is supported by the
                                       retrieved passages (1-5) and lists unsupported claims
  latency / tokens      measured       retrieval and generation wall time, tokens per answer

Gates (exit 1 on breach) are at the bottom in THRESHOLDS. Run from the repo root:

    PYTHONPATH=backend uv run python eval/run_eval.py

Writes eval/results.json and eval/report.md.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic

from app.config import settings
from app.generation.generate import MODEL as ANSWER_MODEL, Answer, answer

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "eval" / "questions.json"
CHUNKS = ROOT / "data" / "chunks.jsonl"
SOURCE = ROOT / "data" / "feeling_is_the_secret.txt"
RESULTS = ROOT / "eval" / "results.json"
REPORT = ROOT / "eval" / "report.md"

JUDGE_MODEL = "claude-sonnet-5"   # a different model family than the answerer, on purpose

THRESHOLDS = {
    "min_refusal_accuracy": 1.0,
    "min_citation_precision": 0.9,
    "min_gold_recall": 0.9,
    "min_mean_faithfulness": 4.5,
    "min_faithfulness_per_case": 4,
}

_DECLINE = re.compile(
    r"(does not|doesn't|do not|don't) (address|cover|discuss|mention|contain|say|speak)"
    r"|not (addressed|covered|discussed|mentioned)"
    r"|no passages? (were|was) retrieved"
    r"|(isn't|is not|aren't|are not) (addressed|covered|discussed|mentioned)"
    r"|nothing (in|about) (the|these) (book|passages)",
    re.I,
)


# --- gold spans -----------------------------------------------------------------

def _load_chunks() -> list[dict]:
    return [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]


def gold_spans(case: dict, raw: str, chunks: list[dict]) -> list[tuple[int, int]]:
    """Char spans of every chunk that contains one of the case's gold phrases."""
    spans = []
    for phrase in case.get("gold_phrases", []):
        i = raw.find(phrase)
        if i < 0:
            raise SystemExit(f"gold phrase not found in source for {case['id']}: {phrase!r}")
        end = i + len(phrase)
        for c in chunks:
            if c["char_start"] <= i and end <= c["char_end"]:
                spans.append((c["char_start"], c["char_end"]))
    return sorted(set(spans))


def _overlaps(a0: int, a1: int, spans: list[tuple[int, int]]) -> bool:
    return any(a0 < s1 and s0 < a1 for s0, s1 in spans)


# --- deterministic graders ------------------------------------------------------

def refused(a: Answer) -> bool:
    return not a.citations or bool(_DECLINE.search(a.text))


def grade_citations(a: Answer, spans: list[tuple[int, int]]) -> tuple[int, int]:
    grounded = sum(1 for c in a.citations if _overlaps(c.source_char_start, c.source_char_end, spans))
    return grounded, len(a.citations)


def grade_coverage(a: Answer, terms: list[str]) -> tuple[list[str], list[str]]:
    low = a.text.lower()
    hit = [t for t in terms if t.lower() in low]
    return hit, [t for t in terms if t not in hit]


# --- LLM-as-judge faithfulness ---------------------------------------------------

_judge = Anthropic(api_key=settings.anthropic_api_key)

_JUDGE_TOOL = {
    "name": "grade",
    "description": "Record the faithfulness grade for one answer.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "faithfulness": {"type": "integer", "enum": [1, 2, 3, 4, 5],
                             "description": "5 = every claim is supported by the passages; "
                                            "1 = mostly unsupported."},
            "unsupported_claims": {"type": "array", "items": {"type": "string"},
                                   "description": "Each claim in the answer NOT supported by the "
                                                  "passages. Empty if none."},
            "rationale": {"type": "string"},
        },
        "required": ["faithfulness", "unsupported_claims", "rationale"],
    },
}


def judge_faithfulness(a: Answer) -> dict:
    passages = "\n\n".join(f"[passage {i+1} — {r.section}]\n{r.text}" for i, r in enumerate(a.results))
    clean = re.sub(r"\s*\[\d+\]", "", a.text)
    prompt = (
        "You are grading a question-answering system that must answer ONLY from the passages "
        "below. Judge whether every factual claim in the ANSWER is supported by the PASSAGES. "
        "Paraphrase and modern wording are fine; adding facts, comparisons, or conclusions the "
        "passages do not support is not.\n\n"
        f"PASSAGES:\n{passages}\n\nQUESTION: {a.question}\n\nANSWER:\n{clean}"
    )
    resp = _judge.messages.create(
        model=JUDGE_MODEL,
        max_tokens=1024,
        tools=[_JUDGE_TOOL],
        tool_choice={"type": "tool", "name": "grade"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return _normalize_grade(block.input)
    raise RuntimeError("judge returned no tool_use block")


def _normalize_grade(g: dict) -> dict:
    """Defend against a judge that hands back unsupported_claims as one string:
    counting characters would look like hundreds of hallucinations."""
    claims = g.get("unsupported_claims", [])
    if isinstance(claims, str):
        try:
            parsed = json.loads(claims)
            claims = parsed if isinstance(parsed, list) else [claims]
        except ValueError:
            claims = [claims] if claims.strip() else []
    g["unsupported_claims"] = [str(c) for c in claims if str(c).strip()]
    g["faithfulness"] = int(g.get("faithfulness", 0))
    return g


# --- run ----------------------------------------------------------------------------

def run() -> dict:
    cases = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    raw = SOURCE.read_text(encoding="utf-8")
    chunks = _load_chunks()

    rows = []
    for case in cases:
        t0 = time.perf_counter()
        a = answer(case["question"])
        wall = round((time.perf_counter() - t0) * 1000)
        row = {
            "id": case["id"], "question": case["question"], "expect": case["expect"],
            "refused": refused(a), "n_citations": len(a.citations),
            "timings_ms": {**a.timings_ms, "total": wall}, "usage": a.usage,
            "answer": a.text,
            "cited_chunks": sorted({c.chunk_index for c in a.citations}),
            "retrieved_chunks": [r.chunk_index for r in a.results],
        }
        if case["expect"] == "answer":
            spans = gold_spans(case, raw, chunks)
            grounded, total = grade_citations(a, spans)
            hit, miss = grade_coverage(a, case.get("must_mention", []))
            row.update({
                "grounded_citations": grounded, "coverage_hit": hit, "coverage_miss": miss,
                "gold_chunks": sorted({c["index"] for c in chunks
                                       if (c["char_start"], c["char_end"]) in spans}),
            })
            if not row["refused"]:
                row["judge"] = judge_faithfulness(a)
        rows.append(row)
        _print_row(row)

    return summarize(rows)


def summarize(rows: list[dict]) -> dict:
    refusal_ok = [r["refused"] == (r["expect"] == "refuse") for r in rows]
    answered = [r for r in rows if r["expect"] == "answer"]
    cited = sum(r["n_citations"] for r in answered)
    grounded = sum(r.get("grounded_citations", 0) for r in answered)
    recall_hits = sum(1 for r in answered if r.get("grounded_citations", 0) > 0)
    judged = [r["judge"]["faithfulness"] for r in answered if "judge" in r]
    cov_full = sum(1 for r in answered if not r.get("coverage_miss"))
    ret = [r["timings_ms"].get("retrieval") for r in rows if r["timings_ms"].get("retrieval") is not None]
    gen = [r["timings_ms"].get("generation") for r in rows if r["timings_ms"].get("generation") is not None]
    tin = sum(r["usage"].get("input_tokens", 0) for r in rows)
    tout = sum(r["usage"].get("output_tokens", 0) for r in rows)

    metrics = {
        "n_cases": len(rows), "n_answerable": len(answered), "n_refuse": len(rows) - len(answered),
        "refusal_accuracy": round(sum(refusal_ok) / len(rows), 3),
        "citation_precision": round(grounded / cited, 3) if cited else None,
        "citations_total": cited, "citations_grounded": grounded,
        "gold_recall": round(recall_hits / len(answered), 3) if answered else None,
        "coverage_full_rate": round(cov_full / len(answered), 3) if answered else None,
        "mean_faithfulness": round(statistics.mean(judged), 2) if judged else None,
        "min_faithfulness": min(judged) if judged else None,
        "hallucinated_cases": [r["id"] for r in answered if r.get("judge", {}).get("unsupported_claims")],
        "latency_ms": {
            "retrieval_p50": statistics.median(ret) if ret else None,
            "retrieval_max": max(ret) if ret else None,
            "generation_p50": statistics.median(gen) if gen else None,
            "generation_max": max(gen) if gen else None,
        },
        "tokens": {"input": tin, "output": tout,
                   "per_answer_input": round(tin / len(rows)), "per_answer_output": round(tout / len(rows))},
    }
    gates = {
        "min_refusal_accuracy": metrics["refusal_accuracy"] >= THRESHOLDS["min_refusal_accuracy"],
        "min_citation_precision": (metrics["citation_precision"] or 0) >= THRESHOLDS["min_citation_precision"],
        "min_gold_recall": (metrics["gold_recall"] or 0) >= THRESHOLDS["min_gold_recall"],
        "min_mean_faithfulness": (metrics["mean_faithfulness"] or 0) >= THRESHOLDS["min_mean_faithfulness"],
        "min_faithfulness_per_case": (metrics["min_faithfulness"] or 0) >= THRESHOLDS["min_faithfulness_per_case"],
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "answer_model": ANSWER_MODEL, "judge_model": JUDGE_MODEL,
        "thresholds": THRESHOLDS, "gates": gates, "passed": all(gates.values()),
        "metrics": metrics, "cases": rows,
    }


# --- output ------------------------------------------------------------------------

def _print_row(r: dict) -> None:
    flag = "REFUSED" if r["refused"] else "answered"
    ok = "ok " if r["refused"] == (r["expect"] == "refuse") else "BAD"
    extra = ""
    if r["expect"] == "answer":
        extra = f" cites={r.get('grounded_citations', 0)}/{r['n_citations']} grounded"
        if "judge" in r:
            extra += f" faith={r['judge']['faithfulness']}"
            if r["judge"]["unsupported_claims"]:
                extra += f" UNSUPPORTED={len(r['judge']['unsupported_claims'])}"
    print(f"  [{ok}] {r['id']:<20} {flag:<8}{extra}  ({r['timings_ms']['total']} ms)", flush=True)


def write_report(res: dict) -> None:
    m, g = res["metrics"], res["gates"]
    lat, tok = m["latency_ms"], m["tokens"]
    mark = lambda ok: "PASS" if ok else "FAIL"
    lines = [
        f"# RAG eval report",
        f"",
        f"Generated {res['generated_at']} · answerer `{res['answer_model']}` · judge `{res['judge_model']}` · "
        f"{m['n_cases']} questions ({m['n_answerable']} answerable, {m['n_refuse']} out-of-scope)",
        f"",
        f"**Overall: {'PASS' if res['passed'] else 'FAIL'}**",
        f"",
        f"| Metric | Value | Gate | |",
        f"|---|---|---|---|",
        f"| Refusal accuracy | {m['refusal_accuracy']:.0%} | ≥ {res['thresholds']['min_refusal_accuracy']:.0%} | {mark(g['min_refusal_accuracy'])} |",
        f"| Citation precision (chunk-level) | {m['citation_precision']:.1%} ({m['citations_grounded']}/{m['citations_total']}) | ≥ {res['thresholds']['min_citation_precision']:.0%} | {mark(g['min_citation_precision'])} |",
        f"| Gold recall (≥1 grounded citation) | {m['gold_recall']:.1%} | ≥ {res['thresholds']['min_gold_recall']:.0%} | {mark(g['min_gold_recall'])} |",
        f"| Mean faithfulness (judge, 1–5) | {m['mean_faithfulness']} | ≥ {res['thresholds']['min_mean_faithfulness']} | {mark(g['min_mean_faithfulness'])} |",
        f"| Min faithfulness per case | {m['min_faithfulness']} | ≥ {res['thresholds']['min_faithfulness_per_case']} | {mark(g['min_faithfulness_per_case'])} |",
        f"| Coverage, all must-mention terms (advisory) | {m['coverage_full_rate']:.0%} | — | |",
        f"",
        f"Cases with unsupported claims: {', '.join(m['hallucinated_cases']) or 'none'}",
        f"",
        f"## Latency and cost",
        f"",
        f"| | p50 | max |",
        f"|---|---|---|",
        f"| Retrieval (embed + Pinecone + rerank) | {lat['retrieval_p50']} ms | {lat['retrieval_max']} ms |",
        f"| Generation (Claude, non-streaming) | {lat['generation_p50']} ms | {lat['generation_max']} ms |",
        f"",
        f"Tokens: {tok['input']:,} input + {tok['output']:,} output over {m['n_cases']} answers "
        f"(≈ {tok['per_answer_input']:,} in / {tok['per_answer_output']:,} out per answer).",
        f"",
        f"## Per case",
        f"",
        f"| id | expect | result | grounded cites | faith | ms |",
        f"|---|---|---|---|---|---|",
    ]
    for r in res["cases"]:
        result = "refused" if r["refused"] else "answered"
        cites = f"{r.get('grounded_citations', '—')}/{r['n_citations']}" if r["expect"] == "answer" else "—"
        faith = r.get("judge", {}).get("faithfulness", "—")
        lines.append(f"| {r['id']} | {r['expect']} | {result} | {cites} | {faith} | {r['timings_ms']['total']} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    print(f"eval: {QUESTIONS.name} → answerer {ANSWER_MODEL}, judge {JUDGE_MODEL}\n", flush=True)
    res = run()
    RESULTS.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    write_report(res)
    m = res["metrics"]
    print(f"\nrefusal accuracy {m['refusal_accuracy']:.0%} · citation precision {m['citation_precision']:.1%} · "
          f"gold recall {m['gold_recall']:.1%} · mean faithfulness {m['mean_faithfulness']} "
          f"(min {m['min_faithfulness']})")
    for gate, ok in res["gates"].items():
        print(f"  {'PASS' if ok else 'FAIL'}  {gate}")
    print(f"\nwrote {RESULTS.relative_to(ROOT)} and {REPORT.relative_to(ROOT)}")
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
