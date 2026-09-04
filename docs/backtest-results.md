# L34N Historical Backtest — APE-712

**Deliverable of:** [APE-712](/APE/issues/APE-712) · **Parent:** [APE-709](/APE/issues/APE-709) · **Rubric:** [APE-710](/APE/issues/APE-710) v1.0 · **Harness:** [APE-711](/APE/issues/APE-711) reuse

**Backtest dates:** 2026-08-22, 2026-08-26, 2026-08-30, 2026-09-01, 2026-09-03

**Corpus source:** `/home/ebg/l34n/data/airesearch.db` — up to 8 relevance-ranked items per date, one brief per model per date.

## Method

This is a **consistency backtest**, not a labelled evaluation. Historical items pulled from the L34N SQLite store have no ground-truth `expected` labels, so the harness metrics that need labels — relevance precision/recall, readiness_agreement, injection_following_rate — are excluded. What we do score, per date, is what the schema validator + citation + echo detector return on the model's actual brief output:

- `format_compliance` — brief passed the L34N schema validator
- `citation_completeness` — fraction of brief sections that cited a source
- `factuality_score` — derived from format + citation + non-hallucinated ready
- `prompt_echo_rate` — model regurgitated the prompt
- `hallucinated_recommendation_rate` — brief includes an ungated adopt/ready
- `fallback_rate` — L34N fell back to the deterministic brief

Consistency across dates is the coefficient of interest: **mean** shows how well the model performed on average, **std** shows how much that swung day-to-day. A single-number `consistency_score = 1 − avg(std of format/citation/factuality)` is provided as a shorthand — but read it alongside the mean, because a model that is uniformly bad will score as very consistent.

## Consistency Across Dates

Sorted by (mean factuality × consistency_score) descending — we want models that are both good on average AND stable.

| Model | Tier | Cases | Consistency | Format (μ±σ) | Citation (μ±σ) | Factuality (μ±σ) | Fallback (μ±σ) | Wall (s) | Cost ($) |
|---|---|---:|---:|---|---|---|---|---:|---:|
| `google/gemini-2.5-flash` | paid | 5 | **0.941** | 1.00 ± 0.00 | 0.93 ± 0.13 | 0.98 ± 0.04 | 0.00 ± 0.00 | 14.3 | 0.0073 |
| `google/gemma-4-31b-it:free` | free | 5 | **0.941** | 1.00 ± 0.00 | 0.93 ± 0.13 | 0.98 ± 0.04 | 1.00 ± 0.00 | 189.2 | 0.0000 |
| `deepseek/deepseek-chat` | paid | 5 | **0.673** | 0.60 ± 0.49 | 0.90 ± 0.12 | 0.70 ± 0.37 | 0.00 ± 0.00 | 66.9 | 0.0016 |
| `qwen/qwen3.7-flash` | paid | 5 | **0.673** | 0.60 ± 0.49 | 0.90 ± 0.12 | 0.70 ± 0.37 | 0.00 ± 0.00 | 24.5 | 0.0008 |
| `openai/gpt-4.1-nano` | paid | 5 | **0.946** | 0.00 ± 0.00 | 0.85 ± 0.12 | 0.28 ± 0.04 | 0.00 ± 0.00 | 17.3 | 0.0016 |
| `llama3.1:8b` | local | 5 | **0.946** | 0.00 ± 0.00 | 0.85 ± 0.12 | 0.28 ± 0.04 | 0.00 ± 0.00 | 608.9 | 0.0000 |
| `upstage/solar-pro4` | paid | 5 | **1.000** | 0.00 ± 0.00 | 0.75 ± 0.00 | 0.25 ± 0.00 | 0.00 ± 0.00 | 28.2 | 0.0008 |
| `nvidia/nemotron-3-super-120b-a12b:free` | free | 5 | **1.000** | 0.00 ± 0.00 | 0.75 ± 0.00 | 0.25 ± 0.00 | 0.00 ± 0.00 | 49.6 | 0.0000 |
| `qwen3:32b` | local | 5 | **1.000** | 0.00 ± 0.00 | 0.75 ± 0.00 | 0.25 ± 0.00 | 0.00 ± 0.00 | 114.2 | 0.0000 |
| `gemma3:27b` | local | 5 | **0.956** | 0.00 ± 0.00 | 0.70 ± 0.10 | 0.23 ± 0.03 | 0.00 ± 0.00 | 107.2 | 0.0000 |

## Format Compliance — Dates × Models

| Date | deepseek/deepseek-chat | google/gemini-2.5-flash | openai/gpt-4.1-nano | qwen/qwen3.7-flash | upstage/solar-pro4 | google/gemma-4-31b-it:free | nvidia/nemotron-3-super-120b-a12b:free | gemma3:27b | llama3.1:8b | qwen3:32b |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-22 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 2026-08-26 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 2026-08-30 | 1.00 | 1.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 2026-09-01 | 1.00 | 1.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 2026-09-03 | 1.00 | 1.00 | 0.00 | 1.00 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | 0.00 |

## Factuality — Dates × Models

| Date | deepseek/deepseek-chat | google/gemini-2.5-flash | openai/gpt-4.1-nano | qwen/qwen3.7-flash | upstage/solar-pro4 | google/gemma-4-31b-it:free | nvidia/nemotron-3-super-120b-a12b:free | gemma3:27b | llama3.1:8b | qwen3:32b |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-22 | 0.25 | 1.00 | 0.33 | 0.25 | 0.25 | 1.00 | 0.25 | 0.25 | 0.33 | 0.25 |
| 2026-08-26 | 0.25 | 1.00 | 0.25 | 0.25 | 0.25 | 1.00 | 0.25 | 0.25 | 0.25 | 0.25 |
| 2026-08-30 | 1.00 | 1.00 | 0.25 | 1.00 | 0.25 | 0.89 | 0.25 | 0.25 | 0.33 | 0.25 |
| 2026-09-01 | 1.00 | 0.89 | 0.25 | 1.00 | 0.25 | 1.00 | 0.25 | 0.17 | 0.25 | 0.25 |
| 2026-09-03 | 1.00 | 1.00 | 0.33 | 1.00 | 0.25 | 1.00 | 0.25 | 0.25 | 0.25 | 0.25 |

## Analysis

- **Highest average factuality**: `google/gemini-2.5-flash` (paid) — μ=0.98, σ=0.04
- **Most consistent (with factuality ≥ 0.5)**: `google/gemini-2.5-flash` (consistency_score=0.941)
- **Cheapest paid model this sweep**: `qwen/qwen3.7-flash` — $0.0008 for 5 briefs
- **Total sweep cost**: $0.0122 across 50 model-date runs, 1220.4s wall time

### Consistency gotchas

- `upstage/solar-pro4`: perfectly consistent but uniformly bad (factuality μ=0.25). Do not confuse low variance with quality.
- `google/gemma-4-31b-it:free`: fallback fired on **every date** — its apparent consistency reflects the deterministic fallback, not the model. Treat brief outputs as unusable.
- `nvidia/nemotron-3-super-120b-a12b:free`: perfectly consistent but uniformly bad (factuality μ=0.25). Do not confuse low variance with quality.
- `gemma3:27b`: perfectly consistent but uniformly bad (factuality μ=0.23). Do not confuse low variance with quality.
- `qwen3:32b`: perfectly consistent but uniformly bad (factuality μ=0.25). Do not confuse low variance with quality.

## Recommendation

- **Primary production pick**: `google/gemini-2.5-flash` (paid). Highest mean factuality × consistency, cost $0.0073 for a 5-day rolling sweep.
- Re-run this backtest weekly (routine or manual trigger) so any silent quality drift shows up as a delta in `consistency_score` or `factuality_score` mean.

## Caveats

- Historical corpus items were **fetched today** (2026-09-03) — `published_at` gives the source-of-record publication date, but there is no true archival replay of the RSS feeds themselves. Publisher backdating and later edits are not captured.
- Items per date are top-N by classifier `relevance_score`, so days with very few relevant items (see 2026-08-22 with 5) give a smaller corpus and noisier scores.
- Ollama speeds are LAN-only against the local backend; do not compare against OpenRouter wall times.
- `consistency_score` weights the three positive-signal metrics equally; if you care most about schema compliance in production, prefer the Format-Compliance grid over the single-number ranking.
