"""Render the APE-711 benchmark report from per-model JSON outputs.

Reads `data/benchmark-results/*.json` (and optional subdirs), renders a
Markdown table + dimension breakdown, and writes it to the target path.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _load_all(dirs: list[Path]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for d in dirs:
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*.json")):
            if path.name == "index.json":
                continue
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            slug = doc.get("model_slug") or path.stem
            if slug in seen:
                continue
            seen.add(slug)
            docs.append(doc)
    return docs


def _fmt(v: Any, decimals: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{decimals}f}"
    except (TypeError, ValueError):
        return str(v)


def _dq_badge(doc: dict[str, Any]) -> str:
    if doc.get("failed"):
        return "**FAILED**"
    r = doc.get("rubric") or {}
    if r.get("disqualified"):
        return "**DQ**"
    c = float(r.get("composite") or 0)
    if c >= 80:
        return "Excellent"
    if c >= 65:
        return "Pass"
    if c >= 50:
        return "Marginal"
    return "Fail"


def render(docs: list[dict[str, Any]]) -> str:
    docs_sorted = sorted(
        docs,
        key=lambda d: -(d.get("rubric") or {}).get("composite", -1) if not d.get("failed") else 999,
    )
    total_cost = sum(d.get("cost_usd_estimate", 0) or 0 for d in docs if not d.get("failed"))
    total_calls = sum((d.get("call_stats") or {}).get("calls", 0) for d in docs if not d.get("failed"))

    lines: list[str] = []
    lines.append("# L34N Model Benchmark — APE-711")
    lines.append("")
    lines.append(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    corpus_v = next((d.get("corpus_version") for d in docs if d.get("corpus_version")), "?")
    prompt_v = next((d.get("prompt_version") for d in docs if d.get("prompt_version")), "?")
    harness_v = next((d.get("harness_version") for d in docs if d.get("harness_version")), "?")
    lines.append(f"**Corpus:** v{corpus_v} · **Prompt:** {prompt_v} · **Harness:** {harness_v}")
    lines.append(f"**Rubric:** [APE-710](/APE/issues/APE-710) v1.0 · **Scoring layer:** `schema`")
    lines.append(f"**Sweep totals:** {len(docs)} models, {total_calls} generations, ${total_cost:.4f} spent")
    lines.append("")
    lines.append("## Composite Ranking")
    lines.append("")
    lines.append("| Rank | Model | Tier | Composite | Verdict | Wall (s) | Cost ($) | DQ |")
    lines.append("|---:|---|---|---:|---|---:|---:|---|")
    rank = 0
    for d in docs_sorted:
        if d.get("failed"):
            continue
        rank += 1
        r = d["rubric"]
        lines.append(
            f"| {rank} | `{d['model_id']}` | {d['tier']} "
            f"| {r['composite']:.2f} | {_dq_badge(d)} "
            f"| {d['wall_clock_s']:.1f} "
            f"| {d['cost_usd_estimate']:.4f} "
            f"| {'yes' if r['disqualified'] else '—'} |"
        )
    lines.append("")

    lines.append("## Per-Dimension Scores")
    lines.append("")
    lines.append("| Model | Relevance | Accuracy | Depth | Actionability | Cost | Speed |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for d in docs_sorted:
        if d.get("failed"):
            continue
        r = d["rubric"]
        lines.append(
            f"| `{d['model_id']}` "
            f"| {r['relevance']:.1f} | {r['accuracy']:.1f} | {r['depth']:.1f} "
            f"| {r['actionability']:.1f} | {r['cost']:.1f} | {r['speed']:.1f} |"
        )
    lines.append("")

    lines.append("## Full-Fidelity Enrichment Metrics")
    lines.append("")
    lines.append("Depth and Actionability scores use these numbers when the "
                 "enrichment pass ran (Critique + Adapt turns, 5 research-tier cases).")
    lines.append("")
    lines.append("| Model | Full-Fidelity | Enrich Cases | Critique Parse | Avg Q | Avg U | Adapt-Complete Rate |")
    lines.append("|---|:-:|---:|---:|---:|---:|---:|")
    for d in docs_sorted:
        if d.get("failed"):
            continue
        enr = d.get("enrichment") or {}
        cases_n = enr.get("cases", 0) if enr else 0
        parsed = enr.get("critique_parse_rate", 0) if enr else 0
        q = enr.get("avg_quality") if enr else None
        u = enr.get("avg_usefulness") if enr else None
        ar = enr.get("adapt_complete_rate", 0) if enr else 0
        lines.append(
            f"| `{d['model_id']}` "
            f"| {'yes' if d.get('full_fidelity') else 'no'} "
            f"| {cases_n} | {_fmt(parsed, 3)} "
            f"| {_fmt(q, 3)} | {_fmt(u, 3)} | {_fmt(ar, 3)} |"
        )
    lines.append("")

    lines.append("## Raw Harness Metrics (schema layer)")
    lines.append("")
    keys = [
        "format_compliance", "citation_completeness", "factuality_score",
        "ai_relevance_precision", "ai_relevance_recall",
        "readiness_agreement", "prompt_echo_rate",
        "hallucinated_recommendation_rate", "injection_following_rate",
        "fallback_rate",
    ]
    lines.append("| Model | " + " | ".join(keys) + " |")
    lines.append("|---|" + "---:|" * len(keys))
    for d in docs_sorted:
        if d.get("failed") or "metrics_by_layer" not in d:
            continue
        m = d["metrics_by_layer"].get("schema") or {}
        row = " | ".join(_fmt(m.get(k, 0), 3) for k in keys)
        lines.append(f"| `{d['model_id']}` | {row} |")
    lines.append("")

    fails = [d for d in docs if d.get("failed")]
    if fails:
        lines.append("## Failures")
        lines.append("")
        for d in fails:
            lines.append(f"- `{d['model_id']}` ({d['tier']}, {d['provider']}) — {d.get('error','?')}")
        lines.append("")

    dq_notes = [d for d in docs
                if not d.get("failed") and (d.get("rubric") or {}).get("disqualifiers")]
    if dq_notes:
        lines.append("## Disqualifier Details")
        lines.append("")
        for d in dq_notes:
            lines.append(f"- `{d['model_id']}`: {'; '.join(d['rubric']['disqualifiers'])}")
        lines.append("")

    lines.append("## Notes & Caveats")
    lines.append("")
    lines.append("- **Depth (full-fidelity)** — when the enrichment pass ran, Depth uses "
                 "the per-case Critique `scores: Q=…` and `U=…` line (parsed from model output), "
                 "combined with the Adapt-page `adapt_complete()` rate and `1 − prompt_echo_rate` "
                 "per the APE-710 formula. Models with `full-fidelity = no` fall back to a proxy "
                 "(format + citation + non-echo) — those depth scores are not directly comparable "
                 "to full-fidelity depth scores.")
    lines.append("- **Actionability (full-fidelity)** — combines `readiness_agreement` (60%) "
                 "with the Adapt-page `adapt_complete()` rate (40%) per rubric §4. Fall-back to "
                 "`readiness_agreement`-only if the enrichment pass did not run.")
    lines.append("- **Cost score** for free/local tier is set to 100 (zero cost). For the paid tier, "
                 "the score is quality-per-dollar normalized against the strongest paid model.")
    lines.append("- **Speed comparability**: OpenRouter latency includes network hops; Ollama latency "
                 "is LAN-only. Do not cross-compare speed across backends.")
    lines.append("- **Enrichment corpus subset** — full-fidelity Depth/Actionability run on the "
                 "5 corpus cases whose `expected.verdict_in` includes adopt/research/spike "
                 "(the 'research-tier' filter per rubric §3): `sum-single-hf`, `model-release-version`, "
                 "`paper-with-code`, `inject-indirect`, `ready-valid-adopt`.")
    lines.append("- Cases: 21 in corpus v1.0.0. Reference: `ai_researcher/eval/corpus.py`.")
    lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render APE-711 benchmark report.")
    ap.add_argument("--in", dest="inputs", action="append",
                    default=None, metavar="DIR",
                    help="input dir with per-model JSONs (repeatable)")
    ap.add_argument("--out",
                    default="/home/ebg/research-pipeline/docs/benchmark-results.md")
    args = ap.parse_args(argv)

    dirs = [Path(p) for p in (args.inputs or [
        "/home/ebg/l34n/data/benchmark-results",
        "/home/ebg/l34n/data/benchmark-results/local",
        "/home/ebg/l34n/data/benchmark-results/paid",
    ])]
    docs = _load_all(dirs)
    if not docs:
        print("no benchmark JSONs found", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(docs), encoding="utf-8")
    print(f"wrote {out_path} ({len(docs)} models)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
