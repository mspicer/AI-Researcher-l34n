# AI Researcher

[![CI](https://github.com/l34n/AI-Researcher/actions/workflows/ci.yml/badge.svg)](https://github.com/l34n/AI-Researcher/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

A single pane of glass for AI: research, model drops, product launches,
acquisitions, tooling, and policy — collected from ~60 sources, clustered into
stories, ranked, and summarised by a local model. Runs entirely on your machine
and is reachable from anywhere on your LAN.

No API keys are required. Local Ollama is the default. Optional Gemini and
OpenRouter keys, when set, take the chat load; embeddings stay local. Every
optional piece degrades to a working fallback.

![The dashboard](docs/screenshot.png)
![Firehose sorted by readiness](docs/firehose.png)
![Adapt brief](docs/adapt.png)
![The dashboard](docs/search.png)
![The dashboard](docs/saved.png)
![The dashboard](docs/sources.png)
![The dashboard](docs/runs.png)

## Quick start

```bash
uv venv && uv pip install -e ".[dev]"
cp .env.example .env          # every default works; edit if you like
ai-researcher run             # first ingest — takes a while, see below
ai-researcher serve           # http://localhost:8899
```

Then install it as a background service:

```bash
./scripts/install-systemd.sh
```

That runs the dashboard continuously and ingests once an hour.

## How it works

```
 sources.yaml ──▶ connectors ──▶ items ──▶ heuristics ──▶ embeddings
                  (9 kinds)       (sqlite)   (all items)    (nomic-embed)
                                                 │              │
                                                 ▼              ▼
                                            model pass ──▶ clustering ──▶ stories
                                            (top N only)   (cosine +     (ranked)
                                                            entity guard)      │
                                                                               ▼
                                              judgment ──▶ readiness gate ──▶ daily brief
                                         (quality / practicality /              │
                                          feasibility / usefulness)              │
                                                                               ▼
                                                              Karpathy wiki (top N)
                                                         ingest → claims → critique
                                                              → adapt → lint
```

**Ingest.** Ten connector kinds — RSS/Atom, Reddit, Hacker News, arXiv, HF
daily papers, HF trending models, GitHub releases, GitHub new-and-hot repos,
Google News (for vendors that publish no feed), and X. Each source's health is
tracked; a broken feed is skipped, never fatal.

**Deduplication.** URLs are canonicalised (tracking params stripped, AMP
suffixes removed, host normalised) so the same story arriving from six places
collapses to one. Identical text collapses too, even when retitled.

**Clustering.** Items are grouped by exact URL/text identity, then by cosine
similarity over embeddings (TF-IDF if no embedding model is installed). A
high-similarity pair naming *disjoint* organisations is blocked from merging —
two labs shipping the same kind of thing on the same day is two stories.

**Ranking.** Engagement is normalised per source, because 400 points on Hacker
News and 400 GitHub stars are not the same quantity. The dominant signal is
corroboration: one outlet is a claim, five independent outlets is a story.

**Enrichment** runs in two passes, because local inference is the scarcest
resource here:

1. Rules classify, tag, and score **every** item instantly. The dashboard is
   never blank and never waits on a queue.
2. The model rewrites only the **top-priority** items — the ones that will
   actually appear on the page — bounded by a count *and* a wall-clock budget.

Set `AIR_ENRICH_BUDGET` / `AIR_ENRICH_TIME_BUDGET` to match your hardware.
Deep research is bounded separately by `AIR_RESEARCH_BUDGET` /
`AIR_RESEARCH_TIME_BUDGET` / `AIR_RESEARCH_THRESHOLD`.

## Commands

| Command | What it does |
|---|---|
| `ai-researcher run` | Full cycle: fetch → enrich → cluster → judge → research → brief |
| `ai-researcher run --no-ingest` | Re-analyse what's stored, no fetching |
| `ai-researcher run --source simonw` | Limit to one source (repeatable) |
| `ai-researcher serve` | Web dashboard |
| `ai-researcher doctor` | Diagnose everything that silently degrades |
| `ai-researcher sources` | Per-source health table |
| `ai-researcher brief` | Print / regenerate today's brief |
| `ai-researcher research` | Re-judge and write deep-research briefs |
| `ai-researcher recluster` | Rebuild stories and topic history |
| `ai-researcher stats` | Counters as JSON |

**`doctor` first** whenever something looks wrong — it reports the model in use,
whether embeddings are available, which credentials are missing, and where
content is stuck.

Dashboard shortcuts: `d` dashboard · `f` firehose · `s` search · `b` saved ·
`a` adapt · `h` sources · `r` runs · `/` focus search.

## Quality gate and Karpathy research

Attention (corroboration, engagement, recency) is the wrong axis for "should I
try this". After clustering, every item is scored on four practitioner
questions — **quality**, **practicality**, **feasibility**, **usefulness** —
first by rules, then by the model for the highest-readiness slice.

The composite `readiness` gates a five-turn wiki, following Karpathy's
raw-sources / wiki / schema pattern:

1. **Ingest** — immutable facts, artifacts, claims as stated
2. **Claims** — demonstrated vs asserted, missing evidence
3. **Critique** — the four scores in prose, plus contradictions
4. **Adapt** — who it's for, prerequisites, first-week experiment, risks, done-looks-like
5. **Lint** — contradictions, orphans, unknowns; the last word on the verdict

Only stories at or above `AIR_RESEARCH_THRESHOLD` (default 0.62) with a
`research` or `adopt` verdict spend a slot. The budget is small on purpose:
five model calls per story. With no model the same pages are filed as a
structured digest so the Adapt tab is never blank.

Open `/adapt` (or press `a`) for the week plans. The dashboard **Ready**
chip, the firehose **Most ready** sort, and the daily brief's
**Ready to build** section all read the same gate. A story that already
has a brief links there as **week plan**.

## API access

**Nothing is required.** Every core source is public and unauthenticated.

| | Status |
|---|---|
| RSS feeds, arXiv, HF papers/models, Hacker News | No key, no limits worth worrying about |
| **GitHub** | Works unauthenticated at 60 req/hr. The connectors make ~30 calls/run, so it's tight. A **classic token with no scopes checked** raises it to 5,000/hr — recommended. |
| **Reddit** | See below. |
| **X / Twitter** | Needs a paid API tier (~$200/mo). The connector stays dormant without `X_BEARER_TOKEN`; everything else is unaffected. |

### Reddit is RSS-only, on purpose

Reddit ended self-serve API key creation with its Responsible Builder Policy.
Every JSON endpoint — `www`, `old`, and `oauth` — returns **403** to an
unauthenticated client, and new script apps can no longer be registered.

The connector therefore uses the public per-subreddit Atom feeds, which still
work. Those are throttled to roughly **one request per minute per IP**, with a
multi-minute penalty box after any burst. So it **rotates**: each run fetches
`per_run` subreddits (default 4) spaced 75s apart, resuming where the last run
stopped. At one run per hour the whole list cycles every 3–4 hours — plenty for
a daily dashboard.

Consequence: Atom carries no score or comment count. Those items are flagged
`no_score`, and the ranker treats that as *unknown* rather than as zero interest,
so they are neither buried nor artificially boosted.

If you ever obtain approved credentials, set `REDDIT_CLIENT_ID` /
`REDDIT_CLIENT_SECRET` and the connector switches to the faster authenticated
path automatically.

## Local model notes

Enrichment and the brief use the workhorse chat backend (Ollama by default,
Gemini Flash or cheap OpenRouter when a key is set). Both degrade gracefully:
no model means heuristic classification and a templated brief, and the
dashboard still works.

Two things dominate throughput on a small GPU:

- **The model must fit entirely in VRAM.** A 7B Q4 needs ~2.9 GiB of weights
  plus ~1.7 GiB of KV cache. On a 6 GiB card Ollama spills a few layers to CPU
  and throughput collapses — measured here at **2.3 tok/s** for a 7B versus
  **7.3 tok/s** for `qwen3:4b`, a 3× difference from model choice alone.
- **Reasoning models must have thinking disabled.** `qwen3` in default mode
  spent its entire token budget thinking and returned an empty response. The
  client sends `think: false`; extraction needs no chain of thought.

Recommended pulls:

```bash
ollama pull qwen3:4b            # chat: fits a 6 GiB card comfortably
ollama pull nomic-embed-text    # embeddings: much better clustering, 274 MB
```

Pin them in `.env` (`OLLAMA_CHAT_MODEL`, `OLLAMA_EMBED_MODEL`) rather than
relying on auto-detect, so an unrelated `ollama pull` can't silently change
which model your dashboard uses.

### Optional cloud chat (Gemini, OpenRouter)

Local Ollama stays the default. Set `GEMINI_API_KEY` and/or `OPENROUTER_API_KEY`
to shift chat off the GPU. Embeddings never leave Ollama (or TF-IDF).

Routing is quality-gated so the cheap model does bulk work and the expensive
one only sees content that already looks worth it:

| Band | Used for | Default |
|---|---|---|
| **Workhorse** | Enrichment summaries, judgment below the readiness gate | Gemini 2.5 Flash, else cheap OpenRouter, else Ollama |
| **Premium** | Deep-research wiki, daily brief, judgment at `AIR_PREMIUM_READINESS` (0.62) | OpenRouter Claude Sonnet, else Gemini 2.5 Pro, else the workhorse |

Pin the model ids in `.env`. Generated Markdown is passed through an unslop
filter (no em dashes, chatbot openers, or the usual AI vocabulary) so a flash
model cannot dump filler into the Adapt tab.

`ai-researcher doctor` prints which backend is the workhorse and which is premium.

Check `nvidia-smi` works. If it reports a driver/library version mismatch, the
kernel module and userspace libraries have drifted — usually after a driver
update without a reboot — and the GPU will underperform until you reboot.

## Network access

`AIR_HOST` defaults to `0.0.0.0`, so the dashboard is reachable at
`http://<your-lan-ip>:8899` from any device on your network.

It has **no authentication by default**. On a trusted home LAN that's usually
fine. To require a token, set `AIR_ACCESS_TOKEN` in `.env` and append
`?k=YOUR_TOKEN` once per browser — it's remembered in a cookie afterwards.

Do not port-forward this to the public internet as-is. Put it behind a
reverse proxy with real authentication, or reach it over Tailscale/WireGuard.

## Tuning sources

`config/sources.yaml` is the whole catalog. Each entry carries a `weight`
(trust multiplier: 2.0 for a lab announcing its own model, 0.6 for a
high-volume aggregator) and an optional `category_hint`.

- Add a blog: append an `{key, name, kind: rss, tier, weight, url}` entry.
- Mute something noisy: set `enabled: false`, or drop its `weight`.
- Track a repo: add it to `gh-releases`' `repos` list.

Changes take effect on the next run. A source removed from the file stops being
fetched but keeps its history.

## Operational notes

**Runs are long and that is by design.** A full cycle is typically 15–25 minutes:
Reddit's rate limit forces ~75s between subreddits, and the model pass spends its
budget at roughly 20s per item on this hardware. Nothing is blocked meanwhile —
the dashboard serves from the database throughout, and every stage commits as it
goes, so an interrupted run leaves consistent data, just less current.

**Only one ingest runs at a time.** `data/ingest.lock` is an exclusive file lock;
a second run exits immediately with `status: busy`. This matters more than it
sounds: two runs driving Ollama concurrently were observed corrupting the
embedding index — unrelated items received byte-identical vectors, which silently
merged unrelated stories. If you see `another ingest run is already active`, that
is the guard working, not an error.

**When clustering looks wrong, check embedding coverage first.** Items without a
vector cannot merge and appear as single-source stories, so partial coverage
looks exactly like broken clustering. `ai-researcher run` reports
`embedded: N new (M total)`; M should track your item count.

**Source quality dominates everything downstream.** A `site:` search over a whole
vendor domain pulls in careers pages and API reference stubs, which then cluster
together into convincing-looking fake stories. The Google News sources are
scoped to blog paths where one is indexed, and the connector filters
non-article pages regardless. If a new source starts producing odd clusters,
look at what it is actually ingesting on the Sources tab before touching the
clustering thresholds.

## Data

Everything lives in `data/airesearch.db` (SQLite, WAL). Items older than
`AIR_RETENTION_DAYS` (120) are pruned automatically — except anything you've
starred, which is kept indefinitely. Back it up by copying the file.

## Contributing

Contributions are welcome — particularly new sources, which usually need a few
lines of YAML and no Python. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
setup, the connector contract, and the one rule that matters most here:
measure before you assert. Most of the non-obvious constants in this codebase
exist because a reasonable assumption turned out to be wrong against the live
service.

Running the tests needs neither a GPU, an API key, nor a network connection:

```bash
uv pip install -e ".[dev]"
python -m pytest
```

## Notes and limits

- **Not affiliated with any of the sources it reads.** It fetches public feeds
  and public API endpoints, identifies itself honestly in its User-Agent, and
  paces itself under each service's published limits.
- **Reddit is RSS-only.** Reddit ended self-serve API key creation with its
  Responsible Builder Policy, so the connector rotates through the public
  per-subreddit Atom feeds instead. Nothing to configure; see the module
  docstring in `connectors/reddit.py` for the measurements behind the pacing.
- **X/Twitter is dormant without a paid token.** The connector exists and stays
  disabled unless `X_BEARER_TOKEN` is set.
- **The dashboard has no authentication by default.** `AIR_ACCESS_TOKEN` adds a
  shared-secret check, but this is built to sit on a trusted LAN. Do not expose
  it directly to the internet.

## License

[MIT](LICENSE) © Kevin Howard
