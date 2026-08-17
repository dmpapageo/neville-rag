# RAG eval report

Generated 2026-08-17T08:03:57+00:00 · answerer `claude-opus-4-8` · judge `claude-sonnet-5` · 20 questions (16 answerable, 4 out-of-scope)

**Overall: PASS**

| Metric | Value | Gate | |
|---|---|---|---|
| Refusal accuracy | 100% | ≥ 100% | PASS |
| Citation precision (chunk-level) | 97.0% (96/99) | ≥ 90% | PASS |
| Gold recall (≥1 grounded citation) | 100.0% | ≥ 90% | PASS |
| Mean faithfulness (judge, 1–5) | 4.94 | ≥ 4.5 | PASS |
| Min faithfulness per case | 4 | ≥ 4 | PASS |
| Coverage, all must-mention terms (advisory) | 100% | — | |

Cases with unsupported claims: faith-is-feeling

## Latency and cost

| | p50 | max |
|---|---|---|
| Retrieval (embed + Pinecone + rerank) | 1596.0 ms | 2624 ms |
| Generation (Claude, non-streaming) | 8066.0 ms | 14659 ms |

Tokens: 78,289 input + 11,158 output over 20 answers (≈ 3,914 in / 558 out per answer).

## Per case

| id | expect | result | grounded cites | faith | ms |
|---|---|---|---|---|---|
| two-aspects | answer | answered | 11/11 | 5 | 17284 |
| how-ideas-impressed | answer | answered | 8/8 | 5 | 10453 |
| dominant-feeling | answer | answered | 4/4 | 5 | 10325 |
| disease-cause | answer | answered | 4/4 | 5 | 8213 |
| servant-vs-wife | answer | answered | 5/5 | 5 | 11265 |
| sleep-role | answer | answered | 11/11 | 5 | 16004 |
| before-sleep | answer | answered | 8/8 | 5 | 12199 |
| body-position | answer | answered | 3/3 | 5 | 7327 |
| signs-follow | answer | answered | 4/5 | 5 | 9423 |
| free-will | answer | answered | 7/7 | 5 | 11535 |
| regret | answer | answered | 5/6 | 5 | 9657 |
| prayer-definition | answer | answered | 8/8 | 5 | 9775 |
| effort-in-prayer | answer | answered | 5/5 | 5 | 11762 |
| passive-state | answer | answered | 6/7 | 5 | 11366 |
| faith-is-feeling | answer | answered | 3/3 | 4 | 7696 |
| no-testimonials | answer | answered | 4/4 | 5 | 9064 |
| refuse-diet | refuse | refused | — | — | 7384 |
| refuse-biography | refuse | refused | — | — | 4699 |
| refuse-investing | refuse | refused | — | — | 4708 |
| refuse-astrology | refuse | refused | — | — | 7013 |
