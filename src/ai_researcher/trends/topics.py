"""Daily topic frequencies and the "what's rising" calculation.

A term is interesting when today's weighted volume departs from its own recent
baseline — not when it is simply common. "OpenAI" appears every day and is never
news; "distillation" tripling overnight is.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from ..db import Database, jload
from ..util import local_day, tokens, utcnow

BASELINE_DAYS = 7
MIN_MENTIONS = 2


def compute_daily_topics(db: Database, day: str | None = None) -> dict[str, Any]:
    """Recompute term weights for one day from that day's enriched items."""
    day = day or local_day()
    rows = db.query(
        """
        SELECT i.id, i.title, i.engagement, i.source_key,
               COALESCE(e.entities, '[]') AS entities,
               COALESCE(e.tags, '[]')     AS tags,
               COALESCE(e.summary, '')    AS summary,
               COALESCE(e.importance, .5) AS importance,
               COALESCE(s.weight, 1.0)    AS source_weight
        FROM items i
        LEFT JOIN enrichment e ON e.item_id = i.id
        LEFT JOIN sources s ON s.key = i.source_key
        WHERE date(COALESCE(i.published_at, i.fetched_at)) = ?
        """,
        (day,),
    )

    counts: dict[str, int] = defaultdict(int)
    weights: dict[str, float] = defaultdict(float)

    for row in rows:
        item_weight = float(row["importance"]) * float(row["source_weight"])
        terms: set[str] = set()
        terms.update(jload(row["entities"], []))
        terms.update(jload(row["tags"], []))
        # Title tokens catch vocabulary the fixed taxonomy has never heard of —
        # which is exactly where a genuinely new trend shows up first.
        terms.update(t for t in tokens(row["title"], min_len=4)[:12])

        for term in terms:
            term = term.strip().lower()
            if len(term) < 3 or len(term) > 48:
                continue
            counts[term] += 1
            weights[term] += item_weight

    with db.tx() as conn:
        conn.execute("DELETE FROM topic_daily WHERE day=?", (day,))
        conn.executemany(
            "INSERT INTO topic_daily (day, term, count, weight) VALUES (?,?,?,?)",
            [(day, term, counts[term], round(weights[term], 4)) for term in counts],
        )
    return {"day": day, "terms": len(counts), "items": len(rows)}


def backfill_topics(db: Database, days: int = 14) -> int:
    """Recompute the trailing window, so a first run has a baseline to compare to."""
    today = utcnow().date()
    for offset in range(days):
        compute_daily_topics(db, (today - timedelta(days=offset)).isoformat())
    return days


def rising_topics(db: Database, day: str | None = None, limit: int = 14) -> list[dict[str, Any]]:
    """Terms whose weight today most exceeds their trailing baseline."""
    day = day or local_day()
    try:
        target = date.fromisoformat(day)
    except ValueError:
        target = utcnow().date()

    start = (target - timedelta(days=BASELINE_DAYS)).isoformat()
    today_rows = db.query(
        "SELECT term, count, weight FROM topic_daily WHERE day=? AND count>=?",
        (day, MIN_MENTIONS),
    )
    if not today_rows:
        return []

    baseline_rows = db.query(
        "SELECT term, AVG(weight) AS avg_w, COUNT(*) AS days_seen "
        "FROM topic_daily WHERE day >= ? AND day < ? GROUP BY term",
        (start, day),
    )
    baseline = {r["term"]: (r["avg_w"] or 0.0, r["days_seen"]) for r in baseline_rows}

    out: list[dict[str, Any]] = []
    for row in today_rows:
        term = row["term"]
        today_w = float(row["weight"])
        avg_w, days_seen = baseline.get(term, (0.0, 0))
        # Smoothing keeps a term that appeared once yesterday from showing an
        # infinite spike today.
        lift = (today_w + 0.5) / (avg_w + 0.5)
        out.append({
            "term": term,
            "count": row["count"],
            "weight": round(today_w, 3),
            "baseline": round(avg_w, 3),
            "lift": round(lift, 2),
            "is_new": days_seen == 0,
        })

    # Rank by lift, but require some absolute volume so noise stays out.
    out.sort(key=lambda t: (t["lift"] * min(1.0, t["weight"] / 2.0)), reverse=True)
    return out[:limit]


def top_entities(db: Database, days: int = 1, limit: int = 12) -> list[dict[str, Any]]:
    """Most-mentioned organisations and models over a window."""
    since = (utcnow().date() - timedelta(days=days - 1)).isoformat()
    rows = db.query(
        """
        SELECT e.entities
        FROM enrichment e
        JOIN items i ON i.id = e.item_id
        WHERE date(COALESCE(i.published_at, i.fetched_at)) >= ?
        """,
        (since,),
    )
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        for entity in jload(row["entities"], []):
            if entity:
                counts[entity] += 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"entity": e, "count": c} for e, c in ranked]


def sparkline_series(db: Database, term: str, days: int = 14) -> list[dict[str, Any]]:
    """Per-day weight for one term, oldest first, with gaps filled as zero."""
    today = utcnow().date()
    start = (today - timedelta(days=days - 1)).isoformat()
    rows = db.query(
        "SELECT day, count, weight FROM topic_daily WHERE term=? AND day>=? ORDER BY day",
        (term.lower(), start),
    )
    known = {r["day"]: (r["count"], r["weight"]) for r in rows}
    series = []
    for offset in range(days - 1, -1, -1):
        d = (today - timedelta(days=offset)).isoformat()
        count, weight = known.get(d, (0, 0.0))
        series.append({"day": d, "count": count, "weight": round(float(weight), 3)})
    return series
