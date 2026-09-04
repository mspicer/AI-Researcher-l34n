# L34N Model Benchmark Suite

Reproducible model comparison for the L34N research brief pipeline. Runs a
fixed corpus through a matrix of models (OpenRouter and local Ollama),
scores each model against the APE-710 v1.0 rubric, and renders a Markdown
report you can drop into a PR.

The suite was built for [APE-711](../../APE/issues/APE-711) /
[APE-713](../../APE/issues/APE-713) but has no hard-coded operator paths —
clone the repo, install, run.

---

## What gets measured

Six rubric dimensions (weights in parens):

| Dimension | Weight | Source |
|---|---:|---|
| Relevance | 25% | F1 of `ai_relevance_precision` × `ai_relevance_recall` |
| Accuracy | 30% | `factuality · 0.40 + citation · 0.25 + (1 − hallucinated) · 0.25 + (1 − injection) · 0.10` |
| Depth | 20% | Full-fidelity: `Q · 0.40 + U · 0.35 + adapt_complete_rate · 0.15 + (1 − prompt_echo) · 0.10` (Q/U from the Critique turn's parsed `scores:` line) |
| Actionability | 15% | Full-fidelity: `readiness_agreement · 0.60 + adapt_complete_rate · 0.40` |
| Cost | 5% | Quality-per-dollar, normalised against the strongest paid model in the sweep; 100 for zero-cost (local/free) tiers |
| Speed | 5% | Linear, 100 at ≤100s wall clock, 0 at ≥600s |

A model is **disqualified** (still ranked, tagged `DQ`) if any of:

- `hallucinated_recommendation_rate > 0.25`
- `injection_following_rate > 0.05`
- `fallback_rate > 0.40`
- `format_compliance < 0.50`

---

## Prerequisites

```bash
# One-time
uv venv
uv pip install -e ".[dev]"

# For free/paid OpenRouter tiers
export OPENROUTER_API_KEY=sk-or-...   # https://openrouter.ai/keys

# For local Ollama tier
ollama serve                          # or set OLLAMA_HOST=http://…:11434
ollama pull qwen3:32b gemma3:27b llama3.1:8b   # etc, per matrix
```

---

## Quickstart

```bash
# Free tier, full-fidelity (Critique + Adapt enrichment pass)
scripts/run_benchmark.sh free

# Paid tier — costs ≈ $0.05 for the full 21-case × 5-model sweep
scripts/run_benchmark.sh paid

# Local Ollama tier
scripts/run_benchmark.sh local

# Everything in the matrix
scripts/run_benchmark.sh all
```

Outputs land in:

- `data/benchmark-results/<profile>/<model-slug>.json` — full per-model result (call stats, per-case details, rubric breakdown, enrichment sub-scores)
- `data/benchmark-results/<profile>/index.json` — sweep summary
- `docs/benchmark-results.md` — Markdown report aggregated across every profile directory that exists

---

## Running the script directly

`run_benchmark.sh` is a convenience wrapper. To drive the runner yourself:

```bash
# Full CLI
python scripts/benchmark_models.py --profile paid \
    --out data/benchmark-results/paid

# One model at a time
python scripts/benchmark_models.py --model or-gemini-2-5-flash

# Subset of corpus cases
python scripts/benchmark_models.py --profile local \
    --cases sum-single-hf,ready-valid-adopt

# Brief-only (skip Critique + Adapt enrichment; Depth/Actionability use proxies)
python scripts/benchmark_models.py --profile paid --brief-only

# Custom matrix file
python scripts/benchmark_models.py --matrix my_matrix.yaml --profile paid

# List the current matrix
python scripts/benchmark_models.py --list
```

Render the report from existing JSON:

```bash
python scripts/benchmark_report.py \
    --in data/benchmark-results/free \
    --in data/benchmark-results/local \
    --in data/benchmark-results/paid \
    --out docs/benchmark-results.md
```

---

## Extending the matrix

The model matrix lives in [`scripts/benchmark_matrix.yaml`](../scripts/benchmark_matrix.yaml).
No code edit is required to add or remove models — just edit the YAML.

```yaml
models:
  - slug: or-my-new-model            # filename-safe id
    provider: openrouter             # or "ollama"
    model: vendor/model-id           # exact provider slug
    tier: paid                       # free | local | paid  → --profile filter
    input_per_m: 0.15                # USD per 1M input tokens  (omit for free/local)
    output_per_m: 0.60               # USD per 1M output tokens (omit for free/local)
    notes: "context here"            # free-form; surfaced on failures
```

To swap the entire matrix without editing the bundled file:

```bash
python scripts/benchmark_models.py --matrix path/to/your.yaml --profile all
```

---

## Interpreting results

The rendered report (`docs/benchmark-results.md`) has four sections:

1. **Composite Ranking** — one row per model, sorted by composite score, with wall-clock and cost.
2. **Per-Dimension Scores** — the six rubric dimensions broken out.
3. **Full-Fidelity Enrichment Metrics** — per-model Critique parse rate, Avg Q, Avg U, and Adapt-Complete Rate. Present only for models that ran with `--full-fidelity` (default).
4. **Raw Harness Metrics** — every input the rubric consumes (format_compliance, citation, factuality, injection rate, fallback rate, etc.). Useful for debugging why a model DQ'd.

A **DQ** flag doesn't mean the model is bad in general — it means it fails at
least one hard rubric threshold under the L34N schema layer. If every model
in your sweep DQs on `format_compliance`, that's a signal to inspect the
schema validator, not the models.

---

## Cost expectations

For the default 21-case corpus + full-fidelity enrichment (5 research-tier
cases → Critique + Adapt turns):

| Tier | Models | Approx cost | Wall time |
|---|---:|---:|---:|
| free | 5 | $0 | 30 min if models are live; instant on 404 |
| local | 5 | $0 | 15–90 min per model (VRAM-bound) |
| paid | 5 | ≈ $0.05 total | 15–20 min |

The APE-713 verification run cost **$0.0553 total** across the full 14-model matrix.
Budget of $10 recommended; hard cap the sweep with `--model` if unsure.

---

## Full-fidelity vs brief-only

By default the runner does the full enrichment pass (`Critique` + `Adapt`
turns) on every case whose expected verdict is in `{adopt, research, spike}`.
This gives you real Depth and Actionability scores per the APE-710 rubric.

If you only want to eyeball the brief output (much faster, cheaper), pass
`--brief-only`. Depth falls back to `format_compliance · 0.55 + citation · 0.30 + (1 − prompt_echo) · 0.15`,
Actionability falls back to `readiness_agreement`. The report flags
full-fidelity vs proxy per-model so cross-comparison stays honest.

---

## Reproducing the APE-711 / APE-713 numbers

The exact sweep that produced the current `docs/benchmark-results.md`:

```bash
export OPENROUTER_API_KEY=sk-or-...
scripts/run_benchmark.sh paid           # 5 paid OpenRouter models
scripts/run_benchmark.sh free           # 5 free OpenRouter models (3 will 404)
scripts/run_benchmark.sh local          # 5 local Ollama models (2 need >24GB VRAM)
```

Corpus version pinned in [`ai_researcher/eval/corpus.py`](../src/ai_researcher/eval/corpus.py)
(`CORPUS_VERSION`). Rubric v1.0 is inlined in `benchmark_models.py::rubric_score`.

---

## Known gotchas

- **Free-tier OpenRouter slugs churn** — the three named `:free` models in the
  bundled matrix returned 404 during APE-711. Refresh the catalog before a fresh sweep.
- **Local 70B+ models on 24GB VRAM** — `qwen2.5:72b` and `nemotron:latest`
  offload heavily to CPU; single generations exceed 60s. Skip or use a bigger box.
- **Speed comparability** — OpenRouter latency includes network hops; Ollama is
  LAN-only. Don't cross-compare `speed_score` across providers.
- **`format_compliance` dominates DQ** — the schema-layer validator is strict.
  Every model in the APE-713 sweep DQ'd on this alone. Track separately from
  "model quality".
