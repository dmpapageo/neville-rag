# RAG eval report

> Archived run, not the current baseline (that is `report.md`, Opus 4.8). The `faith-is-feeling` refusal below was a grader false positive, fixed afterward; regraded, refusal accuracy is 100%. Citation precision still fails at 87.0%, so the app stays on Opus 4.8.

Generated 2026-10-02T13:48:10+00:00 · answerer `claude-opus-5-5` · judge `claude-sonnet-5` · 20 questions (16 answerable, 4 out-of-scope)

**Overall: FAIL**

| Metric | Value | Gate | |
|---|---|---|---|
| Refusal accuracy | 95% | ≥ 100% | FAIL |
| Citation precision (chunk-level) | 87.0% (134/154) | ≥ 90% | FAIL |
| Gold recall (≥1 grounded citation) | 100.0% | ≥ 90% | PASS |
| Mean faithfulness (judge, 1–5) | 4.93 | ≥ 4.5 | PASS |
| Min faithfulness per case | 4 | ≥ 4 | PASS |
| Coverage, all must-mention terms (advisory) | 94% | — | |

Cases with unsupported claims: two-aspects

## Latency and cost

| | p50 | max |
|---|---|---|
| Retrieval (embed + Pinecone + rerank) | 1419.0 ms | 2678 ms |
| Generation (Claude, non-streaming) | 9507.0 ms | 16168 ms |

Tokens: 78,561 input + 14,288 output over 20 answers (≈ 3,928 in / 714 out per answer).

## Per case

| id | expect | result | grounded cites | faith | ms |
|---|---|---|---|---|---|
| two-aspects | answer | answered | 9/11 | 4 | 12265 |
| how-ideas-impressed | answer | answered | 12/13 | 5 | 13609 |
| dominant-feeling | answer | answered | 7/8 | 5 | 10955 |
| disease-cause | answer | answered | 6/8 | 5 | 14039 |
| servant-vs-wife | answer | answered | 12/12 | 5 | 11538 |
| sleep-role | answer | answered | 14/14 | 5 | 14914 |
| before-sleep | answer | answered | 11/11 | 5 | 10866 |
| body-position | answer | answered | 5/5 | 5 | 7731 |
| signs-follow | answer | answered | 5/9 | 5 | 11343 |
| free-will | answer | answered | 12/12 | 5 | 13002 |
| regret | answer | answered | 6/9 | 5 | 10334 |
| prayer-definition | answer | answered | 10/14 | 5 | 17634 |
| effort-in-prayer | answer | answered | 9/10 | 5 | 10892 |
| passive-state | answer | answered | 5/6 | 5 | 11082 |
| faith-is-feeling | answer | refused | 6/7 | — | 8915 |
| no-testimonials | answer | answered | 5/5 | 5 | 6109 |
| refuse-diet | refuse | refused | — | — | 6351 |
| refuse-biography | refuse | refused | — | — | 5227 |
| refuse-investing | refuse | refused | — | — | 6522 |
| refuse-astrology | refuse | refused | — | — | 6261 |
