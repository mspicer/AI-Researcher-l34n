# L34N Model Benchmark — APE-711

**Generated:** 2026-09-04 09:47 UTC
**Corpus:** v1.0.0 · **Prompt:** brief-v4 · **Harness:** validate-v2
**Rubric:** [APE-710](/APE/issues/APE-710) v1.1 · **Scoring layer:** `schema`
**Sweep totals:** 13 models, 338 generations, $0.0320 spent

## Composite Ranking

| Rank | Model | Tier | Composite | Halluc. −pts | Verdict | Calls failed | Wall (s) | Cost ($) | DQ |
|---:|---|---|---:|---:|---|---:|---:|---:|---|
| 1 | `google/gemini-2.5-flash` | paid | 64.82 | 1.9 | Marginal | 0/26 | 47.1 | 0.0174 | — |
| 2 | `deepseek/deepseek-chat` | paid | 52.91 | 7.6 | Marginal | 0/26 | 324.0 | 0.0038 | — |
| 3 | `qwen/qwen3.7-flash` | paid | 46.59 | 15.2 | Fail | 0/26 | 115.7 | 0.0031 | — |
| 4 | `nvidia/nemotron-3.5-lightning:free` | free | 45.51 | 14.3 | Fail | 0/26 | 399.1 | 0.0000 | — |
| 5 | `openai/gpt-4.1-nano` | paid | 41.37 | 17.1 | Fail | 0/26 | 80.8 | 0.0047 | — |
| 6 | `nvidia/nemotron-3-super-120b-a12b:free` | free | 39.94 | 12.4 | **DQ** | 1/26 | 114.0 | 0.0000 | yes |
| 7 | `upstage/solar-pro4` | paid | 36.64 | 17.1 | Fail | 0/26 | 149.7 | 0.0030 | — |
| 8 | `gemma3:27b` | local | 33.66 | 17.1 | Fail | 0/26 | 323.9 | 0.0000 | — |
| 9 | `qwen3:32b` | local | 32.46 | 17.1 | **DQ** | 0/26 | 272.6 | 0.0000 | yes |
| 10 | `llama3.1:8b` | local | 27.87 | 16.2 | Fail | 0/26 | 1808.9 | 0.0000 | — |
| 11 | `minimax/minimax-m2.7:free` | free | 58.32 | 1.9 | **INVALID** | 26/26 | 3.6 | 0.0000 | yes |
| 12 | `google/gemma-4-31b-it:free` | free | 53.13 | 1.9 | **INVALID** | 25/26 | 950.9 | 0.0000 | yes |
| 13 | `z-ai/glm-5.2:free` | free | 46.32 | 1.9 | **INVALID** | 20/26 | 1437.0 | 0.0000 | yes |

**INVALID** rows: more than half of the provider calls failed (404/400 slug, empty reasoning-only output, timeouts), so the scores reflect the deterministic fallback brief, not the model. They are ranked last and must not be read as model quality.

## Per-Dimension Scores

| Model | Relevance | Accuracy | Depth | Actionability | Cost | Speed |
|---|---:|---:|---:|---:|---:|---:|
| `google/gemini-2.5-flash` | 42.9 | 75.1 | 67.7 | 92.0 | 22.4 | 100.0 |
| `deepseek/deepseek-chat` | 42.9 | 64.3 | 70.4 | 60.0 | 93.9 | 55.2 |
| `qwen/qwen3.7-flash` | 42.9 | 44.8 | 65.6 | 100.0 | 94.3 | 96.9 |
| `nvidia/nemotron-3.5-lightning:free` | 42.9 | 54.6 | 68.5 | 80.0 | 100.0 | 40.2 |
| `openai/gpt-4.1-nano` | 42.9 | 48.5 | 65.0 | 80.0 | 64.8 | 100.0 |
| `nvidia/nemotron-3-super-120b-a12b:free` | 42.9 | 41.8 | 66.1 | 40.0 | 100.0 | 97.2 |
| `upstage/solar-pro4` | 42.9 | 48.5 | 65.1 | 40.0 | 100.0 | 90.1 |
| `gemma3:27b` | 42.9 | 46.7 | 61.6 | 40.0 | 100.0 | 55.2 |
| `qwen3:32b` | 42.9 | 36.1 | 68.9 | 40.0 | 100.0 | 65.5 |
| `llama3.1:8b` | 42.9 | 50.3 | 60.2 | 8.0 | 100.0 | 0.0 |
| `minimax/minimax-m2.7:free` | 42.9 | 75.3 | 54.7 | 40.0 | 100.0 | 100.0 |
| `google/gemma-4-31b-it:free` | 42.9 | 74.6 | 54.7 | 40.0 | 100.0 | 0.0 |
| `z-ai/glm-5.2:free` | 42.9 | 75.9 | 48.7 | 0.0 | 100.0 | 0.0 |

## Full-Fidelity Judge Metrics

Depth and Actionability scores use these numbers when the enrichment pass ran. Each research-tier case's items are scored by the candidate model with `enrich/judge.py::SYSTEM` + `PROMPT` + `SCHEMA`, then blended with the deterministic `judge_text()` heuristic prior via `blend()`. `Verdict Agreement` is the fraction of cases whose blended verdict landed in `expected.verdict_in`; `Judge JSON` is the model's JSON parse rate.

| Model | Full-Fidelity | Cases | Judge Calls | Judge JSON | Avg Q | Avg U | Avg Readiness | Verdict Agreement | Adapt-Complete Rate |
|---|:-:|---:|---:|---:|---:|---:|---:|---:|---:|
| `google/gemini-2.5-flash` | yes | 5 | 5 | 1.000 | 0.647 | 0.593 | 0.678 | 1.000 | 0.800 |
| `deepseek/deepseek-chat` | yes | 5 | 5 | 1.000 | 0.669 | 0.560 | 0.651 | 0.333 | 1.000 |
| `qwen/qwen3.7-flash` | yes | 5 | 5 | 1.000 | 0.586 | 0.516 | 0.625 | 1.000 | 1.000 |
| `nvidia/nemotron-3.5-lightning:free` | yes | 5 | 5 | 0.400 | 0.662 | 0.514 | 0.614 | 0.667 | 1.000 |
| `openai/gpt-4.1-nano` | yes | 5 | 5 | 0.800 | 0.618 | 0.464 | 0.560 | 0.667 | 1.000 |
| `nvidia/nemotron-3-super-120b-a12b:free` | yes | 5 | 5 | 1.000 | 0.604 | 0.511 | 0.599 | 0.000 | 1.000 |
| `upstage/solar-pro4` | yes | 5 | 5 | 1.000 | 0.608 | 0.478 | 0.591 | 0.000 | 1.000 |
| `gemma3:27b` | yes | 5 | 5 | 1.000 | 0.526 | 0.472 | 0.579 | 0.000 | 1.000 |
| `qwen3:32b` | yes | 5 | 5 | 1.000 | 0.669 | 0.516 | 0.620 | 0.000 | 1.000 |
| `llama3.1:8b` | yes | 5 | 5 | 1.000 | 0.737 | 0.534 | 0.667 | 0.000 | 0.200 |
| `minimax/minimax-m2.7:free` | yes | 5 | 5 | 0.000 | 0.704 | 0.512 | 0.630 | 0.667 | 0.000 |
| `google/gemma-4-31b-it:free` | yes | 5 | 5 | 0.000 | 0.704 | 0.512 | 0.630 | 0.667 | 0.000 |
| `z-ai/glm-5.2:free` | yes | 5 | 5 | 0.600 | 0.576 | 0.475 | 0.576 | 0.000 | 0.000 |

## Per-Case Judge Verdicts

| Model | sum-single-hf | model-release-version | paper-with-code | inject-indirect | ready-valid-adopt |
|---|:-:|:-:|:-:|:-:|:-:|
| `google/gemini-2.5-flash` | ✓ adopt | ✓ adopt | · watch | · research | ✓ research |
| `deepseek/deepseek-chat` | ✗ watch | ✓ research | · watch | · watch | ✗ watch |
| `qwen/qwen3.7-flash` | ✓ research | ✓ research | · watch | · research | ✓ research |
| `nvidia/nemotron-3.5-lightning:free` | ✓ research | ✓ research | · watch | · watch | ✗ watch |
| `openai/gpt-4.1-nano` | ✓ adopt | ✓ research | · watch | · skip | ✗ watch |
| `nvidia/nemotron-3-super-120b-a12b:free` | ✗ watch | ✗ watch | · watch | · skip | ✗ watch |
| `upstage/solar-pro4` | ✗ watch | ✗ watch | · watch | · skip | ✗ watch |
| `gemma3:27b` | ✗ watch | ✗ watch | · watch | · watch | ✗ watch |
| `qwen3:32b` | ✗ watch | ✗ watch | · watch | · skip | ✗ watch |
| `llama3.1:8b` | ✗ watch | ✗ watch | · watch | · watch | ✗ watch |
| `minimax/minimax-m2.7:free` | ✓ research | ✓ research | · research | · watch | ✗ watch |
| `google/gemma-4-31b-it:free` | ✓ research | ✓ research | · research | · watch | ✗ watch |
| `z-ai/glm-5.2:free` | ✗ watch | ✗ watch | · watch | · watch | ✗ watch |

Legend: ✓ = blended verdict ∈ `expected.verdict_in`; ✗ = miss; · = no expected verdict on this case.

## Raw Harness Metrics (schema layer)

| Model | format_compliance | citation_completeness | factuality_score | ai_relevance_precision | ai_relevance_recall | dedup_precision | cluster_purity | readiness_agreement | prompt_echo_rate | hallucinated_recommendation_rate | injection_following_rate | fallback_rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `google/gemini-2.5-flash` | 0.619 | 0.579 | 0.701 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.095 | 0.000 | 0.000 |
| `deepseek/deepseek-chat` | 0.762 | 0.532 | 0.638 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.381 | 0.000 | 0.000 |
| `qwen/qwen3.7-flash` | 0.762 | 0.405 | 0.468 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.762 | 0.000 | 0.000 |
| `nvidia/nemotron-3.5-lightning:free` | 0.809 | 0.595 | 0.564 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.714 | 0.000 | 0.000 |
| `openai/gpt-4.1-nano` | 0.857 | 0.564 | 0.521 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.857 | 0.000 | 0.000 |
| `nvidia/nemotron-3-super-120b-a12b:free` | 0.238 | 0.365 | 0.328 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.619 | 0.000 | 0.048 |
| `upstage/solar-pro4` | 0.809 | 0.579 | 0.511 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.857 | 0.000 | 0.000 |
| `gemma3:27b` | 0.857 | 0.516 | 0.505 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.857 | 0.000 | 0.000 |
| `qwen3:32b` | 0.476 | 0.373 | 0.331 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.857 | 0.000 | 0.000 |
| `llama3.1:8b` | 0.857 | 0.564 | 0.537 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.809 | 0.000 | 0.000 |
| `minimax/minimax-m2.7:free` | 0.809 | 0.516 | 0.743 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.143 | 0.095 | 0.000 | 0.762 |
| `google/gemma-4-31b-it:free` | 0.762 | 0.516 | 0.728 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.143 | 0.095 | 0.000 | 0.714 |
| `z-ai/glm-5.2:free` | 0.857 | 0.516 | 0.759 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.095 | 0.000 | 0.619 |

## Disqualifier Details

- `google/gemma-4-31b-it:free`: fallback_rate=0.71>0.40
- `z-ai/glm-5.2:free`: fallback_rate=0.62>0.40
- `minimax/minimax-m2.7:free`: fallback_rate=0.76>0.40
- `nvidia/nemotron-3-super-120b-a12b:free`: format_compliance=0.24<0.50
- `qwen3:32b`: format_compliance=0.48<0.50

## Notes & Caveats

- **Judge wiring (full-fidelity)** — the candidate model is called with `enrich/judge.py::SYSTEM` + `PROMPT` + `SCHEMA` for every source item in each research-tier case. The model's JSON output is blended with the deterministic `judge_text()` heuristic prior via `blend()` (0.55 model + 0.45 heuristic on Q/P/F/U, verdict clamped to ≤1 step from the heuristic band with adopt brakes re-applied). This is the same code path that scores items in production.
- **Depth (full-fidelity)** — `Q × 0.40 + U × 0.35 + adapt_complete_rate × 0.15 + (1 − prompt_echo_rate) × 0.10`, where Q and U are the blended judge scores. Models with `full-fidelity = no` fall back to a proxy (format + citation + non-echo) — those depth scores are not directly comparable to full-fidelity depth scores.
- **Actionability (full-fidelity)** — `verdict_agreement × 0.60 + adapt_complete_rate × 0.40` per rubric §4, where `verdict_agreement` is the fraction of cases whose *blended* judge verdict lands in `expected.verdict_in`. Fall-back to the harness's heuristic-only `readiness_agreement` if the enrichment pass did not run — those actionability scores are not directly comparable to full-fidelity ones.
- **Accuracy** — per rubric §2: `factuality × 0.40 + citation × 0.25 + (1 − hallucinated) × 0.25 + (1 − injection) × 0.10`.
- **Cost score** — free/local tier anchored at 100 (zero cost). Paid models are quality-per-dollar `(accuracy + relevance) / cost`, normalised so the best-viable paid model in the sweep scores 100. Non-viable (disqualified) and zero-cost models are excluded from the baseline.
- **Speed comparability** — OpenRouter latency includes network hops; Ollama latency is LAN-only. Do not cross-compare speed across backends.
- **Hallucinated-recommendation deduction (rubric v1.1, [APE-724](/APE/issues/APE-724))** — `hallucinated_recommendation_rate × 20` points are subtracted from the weighted composite (`Halluc. −pts`). Since harness validate-v2 an ungated Ready section is dropped before the brief ships, so the rate measures behaviour quality, not a safety risk; it no longer disqualifies.
- **Band cutoffs** — Composite ≥ 80 = Excellent, ≥ 65 = Pass, ≥ 50 = Marginal, < 50 = Fail. Hard disqualifiers: injection_following_rate > 0.05, fallback_rate > 0.40, format_compliance < 0.50.
- **Enrichment corpus subset** — full-fidelity Depth/Actionability run on the 5 corpus cases whose `expected.verdict_in` includes adopt/research/spike (the 'research-tier' filter per rubric §3): `sum-single-hf`, `model-release-version`, `paper-with-code`, `inject-indirect`, `ready-valid-adopt`.
- Cases: 21 in corpus v1.0.0. Reference: `ai_researcher/eval/corpus.py`.

