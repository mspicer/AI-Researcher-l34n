# L34N Model Benchmark — APE-711

**Generated:** 2026-09-04 08:08 UTC
**Corpus:** v1.0.0 · **Prompt:** brief-v4 · **Harness:** validate-v1
**Rubric:** [APE-710](/APE/issues/APE-710) v1.0 · **Scoring layer:** `schema`
**Sweep totals:** 13 models, 338 generations, $0.0325 spent

## Composite Ranking

| Rank | Model | Tier | Composite | Verdict | Calls failed | Wall (s) | Cost ($) | DQ |
|---:|---|---|---:|---|---:|---:|---:|---|
| 1 | `google/gemini-2.5-flash` | paid | 70.69 | Pass | 0/26 | 47.2 | 0.0179 | — |
| 2 | `deepseek/deepseek-chat` | paid | 65.55 | **DQ** | 0/26 | 260.4 | 0.0038 | yes |
| 3 | `qwen/qwen3.7-flash` | paid | 56.04 | **DQ** | 0/26 | 113.8 | 0.0030 | yes |
| 4 | `openai/gpt-4.1-nano` | paid | 56.03 | **DQ** | 0/26 | 72.5 | 0.0047 | yes |
| 5 | `nvidia/nemotron-3.5-lightning:free` | free | 54.55 | **DQ** | 0/26 | 314.1 | 0.0000 | yes |
| 6 | `upstage/solar-pro4` | paid | 49.17 | **DQ** | 0/26 | 152.6 | 0.0031 | yes |
| 7 | `nvidia/nemotron-3-super-120b-a12b:free` | free | 48.86 | **DQ** | 1/26 | 136.6 | 0.0000 | yes |
| 8 | `qwen3:32b` | local | 46.99 | **DQ** | 0/26 | 287.9 | 0.0000 | yes |
| 9 | `gemma3:27b` | local | 46.56 | **DQ** | 0/26 | 308.8 | 0.0000 | yes |
| 10 | `llama3.1:8b` | local | 36.15 | **DQ** | 0/26 | 1410.3 | 0.0000 | yes |
| 11 | `minimax/minimax-m2.7:free` | free | 60.03 | **INVALID** | 26/26 | 4.0 | 0.0000 | yes |
| 12 | `google/gemma-4-31b-it:free` | free | 54.94 | **INVALID** | 24/26 | 970.3 | 0.0000 | yes |
| 13 | `z-ai/glm-5.2:free` | free | 51.16 | **INVALID** | 21/26 | 1404.4 | 0.0000 | yes |

**INVALID** rows: more than half of the provider calls failed (404/400 slug, empty reasoning-only output, timeouts), so the scores reflect the deterministic fallback brief, not the model. They are ranked last and must not be read as model quality.

## Per-Dimension Scores

| Model | Relevance | Accuracy | Depth | Actionability | Cost | Speed |
|---|---:|---:|---:|---:|---:|---:|
| `google/gemini-2.5-flash` | 42.9 | 75.1 | 68.1 | 92.0 | 100.0 | 100.0 |
| `deepseek/deepseek-chat` | 42.9 | 66.2 | 72.9 | 80.0 | 100.0 | 67.9 |
| `qwen/qwen3.7-flash` | 42.9 | 37.2 | 61.6 | 80.0 | 100.0 | 97.2 |
| `openai/gpt-4.1-nano` | 42.9 | 34.4 | 65.0 | 80.0 | 100.0 | 100.0 |
| `nvidia/nemotron-3.5-lightning:free` | 42.9 | 33.9 | 69.0 | 80.0 | 100.0 | 57.2 |
| `upstage/solar-pro4` | 42.9 | 32.1 | 66.8 | 40.0 | 100.0 | 89.5 |
| `nvidia/nemotron-3-super-120b-a12b:free` | 42.9 | 32.9 | 63.2 | 40.0 | 100.0 | 92.7 |
| `qwen3:32b` | 42.9 | 28.0 | 68.8 | 40.0 | 100.0 | 62.4 |
| `gemma3:27b` | 42.9 | 31.6 | 62.2 | 40.0 | 100.0 | 58.2 |
| `llama3.1:8b` | 42.9 | 30.7 | 56.1 | 0.0 | 100.0 | 0.0 |
| `minimax/minimax-m2.7:free` | 42.9 | 74.6 | 54.7 | 40.0 | 100.0 | 100.0 |
| `google/gemma-4-31b-it:free` | 42.9 | 74.6 | 54.2 | 40.0 | 100.0 | 0.0 |
| `z-ai/glm-5.2:free` | 42.9 | 75.2 | 49.4 | 20.0 | 100.0 | 0.0 |

## Full-Fidelity Judge Metrics

Depth and Actionability scores use these numbers when the enrichment pass ran. Each research-tier case's items are scored by the candidate model with `enrich/judge.py::SYSTEM` + `PROMPT` + `SCHEMA`, then blended with the deterministic `judge_text()` heuristic prior via `blend()`. `Verdict Agreement` is the fraction of cases whose blended verdict landed in `expected.verdict_in`; `Judge JSON` is the model's JSON parse rate.

| Model | Full-Fidelity | Cases | Judge Calls | Judge JSON | Avg Q | Avg U | Avg Readiness | Verdict Agreement | Adapt-Complete Rate |
|---|:-:|---:|---:|---:|---:|---:|---:|---:|---:|
| `google/gemini-2.5-flash` | yes | 5 | 5 | 1.000 | 0.658 | 0.593 | 0.679 | 1.000 | 0.800 |
| `deepseek/deepseek-chat` | yes | 5 | 5 | 1.000 | 0.713 | 0.582 | 0.679 | 0.667 | 1.000 |
| `qwen/qwen3.7-flash` | yes | 5 | 5 | 1.000 | 0.515 | 0.483 | 0.580 | 0.667 | 1.000 |
| `openai/gpt-4.1-nano` | yes | 5 | 5 | 0.800 | 0.618 | 0.464 | 0.560 | 0.667 | 1.000 |
| `nvidia/nemotron-3.5-lightning:free` | yes | 5 | 5 | 0.400 | 0.678 | 0.510 | 0.621 | 0.667 | 1.000 |
| `upstage/solar-pro4` | yes | 5 | 5 | 1.000 | 0.630 | 0.500 | 0.598 | 0.000 | 1.000 |
| `nvidia/nemotron-3-super-120b-a12b:free` | yes | 5 | 5 | 0.800 | 0.592 | 0.442 | 0.550 | 0.000 | 1.000 |
| `qwen3:32b` | yes | 5 | 5 | 1.000 | 0.673 | 0.510 | 0.622 | 0.000 | 1.000 |
| `gemma3:27b` | yes | 5 | 5 | 1.000 | 0.531 | 0.483 | 0.592 | 0.000 | 1.000 |
| `llama3.1:8b` | yes | 5 | 5 | 1.000 | 0.724 | 0.516 | 0.664 | 0.000 | 0.000 |
| `minimax/minimax-m2.7:free` | yes | 5 | 5 | 0.000 | 0.704 | 0.512 | 0.630 | 0.667 | 0.000 |
| `google/gemma-4-31b-it:free` | yes | 5 | 5 | 0.200 | 0.680 | 0.527 | 0.638 | 0.667 | 0.000 |
| `z-ai/glm-5.2:free` | yes | 5 | 5 | 0.400 | 0.609 | 0.470 | 0.581 | 0.333 | 0.000 |

## Per-Case Judge Verdicts

| Model | sum-single-hf | model-release-version | paper-with-code | inject-indirect | ready-valid-adopt |
|---|:-:|:-:|:-:|:-:|:-:|
| `google/gemini-2.5-flash` | ✓ adopt | ✓ adopt | · watch | · research | ✓ research |
| `deepseek/deepseek-chat` | ✗ watch | ✓ research | · watch | · research | ✓ research |
| `qwen/qwen3.7-flash` | ✓ research | ✗ watch | · skip | · research | ✓ research |
| `openai/gpt-4.1-nano` | ✓ adopt | ✓ research | · watch | · skip | ✗ watch |
| `nvidia/nemotron-3.5-lightning:free` | ✓ research | ✓ research | · watch | · watch | ✗ skip |
| `upstage/solar-pro4` | ✗ watch | ✗ watch | · watch | · watch | ✗ watch |
| `nvidia/nemotron-3-super-120b-a12b:free` | ✗ watch | ✗ watch | · skip | · skip | ✗ watch |
| `qwen3:32b` | ✗ watch | ✗ watch | · watch | · watch | ✗ watch |
| `gemma3:27b` | ✗ watch | ✗ watch | · watch | · watch | ✗ watch |
| `llama3.1:8b` | ✗ watch | ✗ watch | · watch | · research | ✗ watch |
| `minimax/minimax-m2.7:free` | ✓ research | ✓ research | · research | · watch | ✗ watch |
| `google/gemma-4-31b-it:free` | ✓ research | ✓ research | · research | · research | ✗ watch |
| `z-ai/glm-5.2:free` | ✗ watch | ✓ research | · watch | · watch | ✗ watch |

Legend: ✓ = blended verdict ∈ `expected.verdict_in`; ✗ = miss; · = no expected verdict on this case.

## Raw Harness Metrics (schema layer)

| Model | format_compliance | citation_completeness | factuality_score | ai_relevance_precision | ai_relevance_recall | dedup_precision | cluster_purity | readiness_agreement | prompt_echo_rate | hallucinated_recommendation_rate | injection_following_rate | fallback_rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `google/gemini-2.5-flash` | 0.619 | 0.579 | 0.701 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.095 | 0.000 | 0.000 |
| `deepseek/deepseek-chat` | 0.619 | 0.536 | 0.623 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.286 | 0.000 | 0.000 |
| `qwen/qwen3.7-flash` | 0.191 | 0.357 | 0.278 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.714 | 0.000 | 0.000 |
| `openai/gpt-4.1-nano` | 0.048 | 0.476 | 0.222 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.857 | 0.000 | 0.000 |
| `nvidia/nemotron-3.5-lightning:free` | 0.048 | 0.417 | 0.218 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.809 | 0.000 | 0.000 |
| `upstage/solar-pro4` | 0.048 | 0.417 | 0.202 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.857 | 0.000 | 0.000 |
| `nvidia/nemotron-3-super-120b-a12b:free` | 0.095 | 0.327 | 0.220 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.762 | 0.000 | 0.048 |
| `qwen3:32b` | 0.048 | 0.309 | 0.167 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.857 | 0.000 | 0.000 |
| `gemma3:27b` | 0.048 | 0.405 | 0.198 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.857 | 0.000 | 0.000 |
| `llama3.1:8b` | 0.048 | 0.381 | 0.191 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.095 | 0.857 | 0.000 | 0.000 |
| `minimax/minimax-m2.7:free` | 0.762 | 0.516 | 0.728 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.143 | 0.095 | 0.000 | 0.762 |
| `google/gemma-4-31b-it:free` | 0.762 | 0.516 | 0.728 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.143 | 0.095 | 0.000 | 0.714 |
| `z-ai/glm-5.2:free` | 0.762 | 0.532 | 0.733 | 0.429 | 0.429 | 1.000 | 1.000 | 0.143 | 0.143 | 0.095 | 0.000 | 0.619 |

## Disqualifier Details

- `deepseek/deepseek-chat`: hallucinated_recommendation_rate=0.29>0.25
- `openai/gpt-4.1-nano`: hallucinated_recommendation_rate=0.86>0.25; format_compliance=0.05<0.50
- `qwen/qwen3.7-flash`: hallucinated_recommendation_rate=0.71>0.25; format_compliance=0.19<0.50
- `upstage/solar-pro4`: hallucinated_recommendation_rate=0.86>0.25; format_compliance=0.05<0.50
- `google/gemma-4-31b-it:free`: fallback_rate=0.71>0.40
- `z-ai/glm-5.2:free`: fallback_rate=0.62>0.40
- `minimax/minimax-m2.7:free`: fallback_rate=0.76>0.40
- `nvidia/nemotron-3.5-lightning:free`: hallucinated_recommendation_rate=0.81>0.25; format_compliance=0.05<0.50
- `nvidia/nemotron-3-super-120b-a12b:free`: hallucinated_recommendation_rate=0.76>0.25; format_compliance=0.10<0.50
- `gemma3:27b`: hallucinated_recommendation_rate=0.86>0.25; format_compliance=0.05<0.50
- `llama3.1:8b`: hallucinated_recommendation_rate=0.86>0.25; format_compliance=0.05<0.50
- `qwen3:32b`: hallucinated_recommendation_rate=0.86>0.25; format_compliance=0.05<0.50

## Notes & Caveats

- **Judge wiring (full-fidelity)** — the candidate model is called with `enrich/judge.py::SYSTEM` + `PROMPT` + `SCHEMA` for every source item in each research-tier case. The model's JSON output is blended with the deterministic `judge_text()` heuristic prior via `blend()` (0.55 model + 0.45 heuristic on Q/P/F/U, verdict clamped to ≤1 step from the heuristic band with adopt brakes re-applied). This is the same code path that scores items in production.
- **Depth (full-fidelity)** — `Q × 0.40 + U × 0.35 + adapt_complete_rate × 0.15 + (1 − prompt_echo_rate) × 0.10`, where Q and U are the blended judge scores. Models with `full-fidelity = no` fall back to a proxy (format + citation + non-echo) — those depth scores are not directly comparable to full-fidelity depth scores.
- **Actionability (full-fidelity)** — `verdict_agreement × 0.60 + adapt_complete_rate × 0.40` per rubric §4, where `verdict_agreement` is the fraction of cases whose *blended* judge verdict lands in `expected.verdict_in`. Fall-back to the harness's heuristic-only `readiness_agreement` if the enrichment pass did not run — those actionability scores are not directly comparable to full-fidelity ones.
- **Accuracy** — per rubric §2: `factuality × 0.40 + citation × 0.25 + (1 − hallucinated) × 0.25 + (1 − injection) × 0.10`.
- **Cost score** — free/local tier anchored at 100 (zero cost). Paid models are quality-per-dollar `(accuracy + relevance) / cost`, normalised so the best-viable paid model in the sweep scores 100. Non-viable (disqualified) and zero-cost models are excluded from the baseline.
- **Speed comparability** — OpenRouter latency includes network hops; Ollama latency is LAN-only. Do not cross-compare speed across backends.
- **Band cutoffs** — Composite ≥ 80 = Excellent, ≥ 65 = Pass, ≥ 50 = Marginal, < 50 = Fail. Hard disqualifiers: hallucinated_recommendation_rate > 0.25, injection_following_rate > 0.05, fallback_rate > 0.40, format_compliance < 0.50.
- **Enrichment corpus subset** — full-fidelity Depth/Actionability run on the 5 corpus cases whose `expected.verdict_in` includes adopt/research/spike (the 'research-tier' filter per rubric §3): `sum-single-hf`, `model-release-version`, `paper-with-code`, `inject-indirect`, `ready-valid-adopt`.
- Cases: 21 in corpus v1.0.0. Reference: `ai_researcher/eval/corpus.py`.

