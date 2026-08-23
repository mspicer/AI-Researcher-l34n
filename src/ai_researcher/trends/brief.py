"""The daily briefing.

One short written read at the top of the dashboard, generated from the day's
top clusters. With no model available it still renders — as a structured
digest rather than prose — because an empty hero panel makes the whole page
look broken.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..config import CATEGORY_LABELS
from ..db import Database, jload
from ..sanitize import UNTRUSTED_RULE, fence
from ..util import iso, local_day, truncate, utcnow
from ..enrich.ollama import OllamaClient
from .topics import rising_topics

log = logging.getLogger("ai_researcher.brief")

SYSTEM = (
    "You write a daily AI briefing for one senior practitioner. You are factual "
    "and compressed. You only use the items provided; you never invent a detail, "
    "a number, or a company. You write in plain prose, no marketing register.\n"
    "Output ONLY the finished briefing in Markdown. Your reply must begin with "
    "the characters '## ' and nothing else. Never narrate your reasoning, never "
    "address the reader, never mention the instructions or the list you were given. "
    + UNTRUSTED_RULE
)

PROMPT = """Below are today's top AI stories, already ranked. Write the briefing.

{stories}

Rising terms today: {rising}

Ready to build (already quality-gated; only mention these in the last section):
{ready}

Write exactly this structure in Markdown:

## The one thing
One paragraph, 2-3 sentences, on the single most consequential item and why.

## Also today
4-6 bullets. Each: **bold 3-6 word label** then one sentence. Cover different
stories, not variations of the first one.

## Worth a closer look
2-3 bullets on things that are less loud but likely to matter — a paper, a
tool, a shift in direction.

## Ready to build
If ready items are listed above, 2-3 bullets. Each: **adopt** or **spike**
then one sentence on the first experiment. Omit this section if none.

Rules: no preamble, no closing summary, no hedging phrases like "it seems".
Refer only to what is listed above. Keep the whole thing under 360 words.
Start your reply with "## The one thing" — no text before it.
"""


def _collect_stories(db: Database, day: str, limit: int = 10) -> list[dict[str, Any]]:
    rows = db.query(
        """
        SELECT c.id, c.label, c.summary, c.category, c.score, c.size,
               c.source_count, c.entities
        FROM clusters c
        WHERE c.day = ?
        ORDER BY c.score DESC
        LIMIT ?
        """,
        (day, limit),
    )
    stories = []
    for row in rows:
        sources = db.query(
            """
            SELECT COALESCE(s.name, i.source_key) AS name
            FROM cluster_items ci
            JOIN items i ON i.id = ci.item_id
            LEFT JOIN sources s ON s.key = i.source_key
            WHERE ci.cluster_id = ?
            LIMIT 6
            """,
            (row["id"],),
        )
        stories.append({
            "label": row["label"],
            "summary": row["summary"],
            "category": row["category"],
            "size": row["size"],
            "source_count": row["source_count"],
            "entities": jload(row["entities"], []),
            "sources": sorted({s["name"] for s in sources}),
        })
    return stories


def _render_prompt_stories(stories: list[dict[str, Any]]) -> str:
    lines = []
    for i, s in enumerate(stories, 1):
        label = CATEGORY_LABELS.get(s["category"], s["category"])
        covered = f"{s['source_count']} sources" if s["source_count"] > 1 else s["sources"][0] if s["sources"] else "1 source"
        lines.append(
            f"{i}. [{label}]\n"
            f"{fence('STORY', s['label'], limit=110)}\n"
            f"{fence('SUMMARY', s['summary'], limit=150)}\n"
            f"   covered by: {covered}"
        )
    return "\n".join(lines)


def _collect_ready(db: Database, limit: int = 5) -> list[dict[str, Any]]:
    rows = db.query(
        """
        SELECT r.title, r.decision, r.verdict, r.readiness
        FROM research r
        WHERE r.status = 'complete'
        ORDER BY CASE r.decision
                    WHEN 'adopt' THEN 0
                    WHEN 'spike' THEN 1
                    ELSE 2 END,
                 r.readiness DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [dict(r) for r in rows]


def _render_ready(ready: list[dict[str, Any]]) -> str:
    if not ready:
        return "none"
    lines = []
    for item in ready:
        decision = item.get("decision") or item.get("verdict") or "watch"
        lines.append(
            f"- [{decision}] {fence('READY', item.get('title') or '', limit=110)} "
            f"(readiness {float(item.get('readiness') or 0):.2f})"
        )
    return "\n".join(lines)


def _fallback_markdown(
    stories: list[dict[str, Any]],
    rising: list[dict[str, Any]],
    ready: list[dict[str, Any]] | None = None,
) -> str:
    if not stories:
        return (
            "## No stories yet\n\n"
            "No items have been clustered for today. Run an ingest "
            "(`ai-researcher run`) or check source health on the Sources tab."
        )
    lead = stories[0]
    parts = [
        "## The one thing\n",
        f"**{lead['label']}** — {lead['summary'] or 'See the linked source.'}"
        f" Covered by {lead['source_count']} source(s).\n",
        "\n## Also today\n",
    ]
    for s in stories[1:7]:
        label = CATEGORY_LABELS.get(s["category"], s["category"])
        parts.append(f"- **{label}** — {truncate(s['label'], 140)}")
    if rising:
        parts.append("\n## Rising terms\n")
        parts.append(", ".join(f"`{t['term']}` ({t['lift']}×)" for t in rising[:8]))
    if ready:
        parts.append("\n## Ready to build\n")
        for item in ready[:4]:
            decision = item.get("decision") or item.get("verdict") or "spike"
            parts.append(f"- **{decision}** — {truncate(item.get('title') or '', 140)}")
    parts.append(
        "\n\n---\n*Generated without a language model — install an Ollama chat "
        "model for written analysis.*"
    )
    return "\n".join(parts)


async def generate_brief(
    db: Database, client: OllamaClient, *, day: str | None = None, force: bool = False
) -> dict[str, Any]:
    day = day or local_day()

    if not force:
        existing = db.one("SELECT day FROM briefs WHERE day=?", (day,))
        if existing:
            return {"day": day, "status": "cached"}

    stories = _collect_stories(db, day)
    rising = rising_topics(db, day, limit=10)
    ready = _collect_ready(db)

    markdown = ""
    model_used = ""
    if stories and await client.probe():
        prompt = PROMPT.format(
            stories=_render_prompt_stories(stories),
            rising=", ".join(f"{t['term']} ({t['lift']}x)" for t in rising[:8]) or "none",
            ready=_render_ready(ready),
        )
        # The brief is the single most valuable model output of a run, and it
        # is one call per day — worth a much longer leash than per-item work.
        text = await client.generate_text(
            prompt, system=SYSTEM, num_predict=850, temperature=0.35,
            timeout=max(600.0, float(client.settings.ollama_timeout)),
        )
        if text and len(text) > 120:
            markdown = _clean(text)
            model_used = client.chat_model

    if not markdown:
        markdown = _fallback_markdown(stories, rising, ready)

    db.execute(
        "INSERT INTO briefs (day, markdown, model, created_at) VALUES (?,?,?,?) "
        "ON CONFLICT(day) DO UPDATE SET markdown=excluded.markdown, "
        "model=excluded.model, created_at=excluded.created_at",
        (day, markdown, model_used, iso(utcnow())),
    )
    return {"day": day, "status": "generated", "model": model_used, "stories": len(stories)}


# Small instruct models routinely prepend their working-out ("Okay, the user
# wants...") despite being told not to, and thinking-mode tags leak on some
# builds. The document always starts at its first heading, so anything before
# that is scaffolding by definition.
_LEAD_NOISE = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


def _clean(text: str) -> str:
    """Reduce a model reply to just the briefing document."""
    text = _LEAD_NOISE.sub("", text.strip())

    if text.startswith("```"):
        text = re.sub(r"^```(?:markdown|md)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)

    # Cut to the first Markdown heading — that is where the briefing begins.
    match = re.search(r"^#{1,3} \S", text, re.MULTILINE)
    if match:
        text = text[match.start():]
    else:
        # No heading at all: drop obvious narration lines rather than ship them.
        lines = [
            ln for ln in text.splitlines()
            if not re.match(r"^\s*(okay|alright|sure|first|now|let me|i(?:'ll| will| need)|"
                            r"the user|here(?:'s| is)|to summar)", ln, re.IGNORECASE)
        ]
        text = "\n".join(lines)

    # Trim trailing self-commentary after the last real content line.
    text = re.sub(r"\n\s*(note|disclaimer|word count)\s*:.*$", "", text,
                  flags=re.IGNORECASE | re.DOTALL)
    return text.strip()
