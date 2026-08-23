"""Read-side queries for the dashboard. No writes happen here."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..config import CATEGORY_LABELS
from ..db import Database, jload
from ..util import domain_of, humanize_age, local_day, parse_datetime, utcnow

ITEM_SELECT = """
    SELECT i.id, i.title, i.url, i.author, i.published_at, i.fetched_at,
           i.engagement, i.comments, i.source_key, i.meta, i.body,
           COALESCE(e.summary, '')     AS summary,
           COALESCE(e.category, '')    AS category,
           COALESCE(e.entities, '[]')  AS entities,
           COALESCE(e.tags, '[]')      AS tags,
           COALESCE(e.importance, 0.5) AS importance,
           COALESCE(e.why, '')         AS why,
           COALESCE(j.quality, 0)      AS quality,
           COALESCE(j.practicality, 0) AS practicality,
           COALESCE(j.feasibility, 0)  AS feasibility,
           COALESCE(j.usefulness, 0)   AS usefulness,
           COALESCE(j.readiness, 0)    AS readiness,
           COALESCE(j.verdict, '')     AS verdict,
           COALESCE(j.artifacts, '[]') AS artifacts,
           COALESCE(r.id, 0)           AS research_id,
           COALESCE(r.decision, '')    AS research_decision,
           COALESCE(s.name, i.source_key) AS source_name,
           COALESCE(s.tier, 'news')    AS tier,
           COALESCE(s.weight, 1.0)     AS source_weight,
           (sv.item_id IS NOT NULL)    AS is_saved
    FROM items i
    LEFT JOIN enrichment e ON e.item_id = i.id
    LEFT JOIN judgments j  ON j.item_id = i.id
    LEFT JOIN research r   ON r.item_id = i.id AND r.status = 'complete'
    LEFT JOIN sources s    ON s.key = i.source_key
    LEFT JOIN saved sv     ON sv.item_id = i.id
"""


def _shape_item(row, now=None) -> dict[str, Any]:
    now = now or utcnow()
    published = parse_datetime(row["published_at"] or row["fetched_at"])
    meta = jload(row["meta"], {})
    item = {
        "id": row["id"],
        "title": row["title"] or "(untitled)",
        "url": row["url"],
        "author": row["author"],
        "summary": row["summary"],
        "why": row["why"],
        "category": row["category"] or "opinion-analysis",
        "category_label": CATEGORY_LABELS.get(row["category"], "Other"),
        "entities": jload(row["entities"], []),
        "tags": jload(row["tags"], []),
        "importance": round(float(row["importance"]), 2),
        "quality": round(float(row["quality"] or 0), 2),
        "practicality": round(float(row["practicality"] or 0), 2),
        "feasibility": round(float(row["feasibility"] or 0), 2),
        "usefulness": round(float(row["usefulness"] or 0), 2),
        "readiness": round(float(row["readiness"] or 0), 2),
        "verdict": row["verdict"] or "",
        "artifacts": jload(row["artifacts"], []),
        "research_id": int(row["research_id"] or 0),
        "research_decision": row["research_decision"] or "",
        "source_key": row["source_key"],
        "source_name": row["source_name"],
        "tier": row["tier"],
        "engagement": int(row["engagement"] or 0),
        "comments": int(row["comments"] or 0),
        "published_at": row["published_at"],
        "age": humanize_age(published, now=now),
        # Google News links are redirect wrappers; show who actually
        # published the piece, not news.google.com.
        "domain": meta.get("display_domain") or domain_of(row["url"]),
        "is_saved": bool(row["is_saved"]),
        "meta": meta,
        # Community items have a discussion URL distinct from the link target.
        "discussion_url": meta.get("permalink") or meta.get("hn_url") or meta.get("tweet_url") or "",
    }
    if not item["summary"]:
        body = (row["body"] or "").strip()
        item["summary"] = (body[:220] + "…") if len(body) > 220 else body
    return item


def top_stories(
    db: Database, *, day: str | None = None, limit: int = 30,
    category: str | None = None, min_sources: int = 0,
) -> list[dict[str, Any]]:
    day = day or local_day()
    now = utcnow()

    where = ["c.day = ?"]
    params: list[Any] = [day]
    if category:
        where.append("c.category = ?")
        params.append(category)
    if min_sources > 1:
        where.append("c.source_count >= ?")
        params.append(min_sources)

    rows = db.query(
        f"""
        SELECT c.id, c.label, c.summary, c.category, c.score, c.size,
               c.source_count, c.entities, c.first_seen, c.last_seen
        FROM clusters c
        WHERE {' AND '.join(where)}
        ORDER BY c.score DESC
        LIMIT ?
        """,
        tuple(params + [limit]),
    )

    stories = []
    for row in rows:
        item_rows = db.query(
            ITEM_SELECT + """
            JOIN cluster_items ci ON ci.item_id = i.id
            WHERE ci.cluster_id = ?
            ORDER BY ci.is_primary DESC, i.engagement DESC,
                     COALESCE(i.published_at, i.fetched_at) DESC
            """,
            (row["id"],),
        )
        items = [_shape_item(r, now) for r in item_rows]
        if not items:
            continue
        stories.append({
            "id": row["id"],
            "label": row["label"],
            "summary": row["summary"] or items[0]["summary"],
            "category": row["category"] or "opinion-analysis",
            "category_label": CATEGORY_LABELS.get(row["category"], "Other"),
            "score": round(float(row["score"]), 3),
            "size": row["size"],
            "source_count": row["source_count"],
            "entities": jload(row["entities"], []),
            "age": humanize_age(parse_datetime(row["last_seen"]), now=now),
            "primary": items[0],
            "items": items,
            "others": items[1:],
            "sources": sorted({i["source_name"] for i in items}),
            "quality": items[0]["quality"],
            "practicality": items[0]["practicality"],
            "feasibility": items[0]["feasibility"],
            "usefulness": items[0]["usefulness"],
            "readiness": items[0]["readiness"],
            "verdict": items[0]["verdict"],
            "research_id": items[0]["research_id"],
            "research_decision": items[0]["research_decision"],
        })
    return stories


def list_items(
    db: Database, *, hours: int = 48, category: str | None = None,
    source_key: str | None = None, tier: str | None = None,
    saved_only: bool = False, ids: list[int] | None = None,
    order: str = "recent", limit: int = 120, offset: int = 0,
) -> list[dict[str, Any]]:
    now = utcnow()
    where: list[str] = []
    params: list[Any] = []

    if ids is not None:
        if not ids:
            return []
        where.append(f"i.id IN ({','.join('?' * len(ids))})")
        params.extend(ids)
    else:
        where.append("COALESCE(i.published_at, i.fetched_at) >= ?")
        params.append((now - timedelta(hours=hours)).isoformat(timespec="seconds"))

    if category:
        where.append("e.category = ?")
        params.append(category)
    if source_key:
        where.append("i.source_key = ?")
        params.append(source_key)
    if tier:
        where.append("s.tier = ?")
        params.append(tier)
    if saved_only:
        where.append("sv.item_id IS NOT NULL")

    order_sql = {
        "recent": "COALESCE(i.published_at, i.fetched_at) DESC",
        "important": "e.importance DESC, COALESCE(i.published_at, i.fetched_at) DESC",
        "engagement": "i.engagement DESC",
    }.get(order, "COALESCE(i.published_at, i.fetched_at) DESC")

    sql = ITEM_SELECT
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order_sql} LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    return [_shape_item(r, now) for r in db.query(sql, tuple(params))]


def search_items(db: Database, text: str, limit: int = 100) -> list[dict[str, Any]]:
    ids = db.search_ids(text, limit=limit)
    if not ids:
        return []
    items = list_items(db, ids=ids, limit=limit)
    # Preserve relevance order from the FTS ranking.
    position = {item_id: i for i, item_id in enumerate(ids)}
    items.sort(key=lambda it: position.get(it["id"], 10**6))
    return items


def model_drops(db: Database, *, days: int = 7, limit: int = 20) -> list[dict[str, Any]]:
    """Recent model releases, newest first — the panel people check first."""
    now = utcnow()
    rows = db.query(
        ITEM_SELECT + """
        WHERE e.category = 'model-release'
          AND COALESCE(i.published_at, i.fetched_at) >= ?
        ORDER BY COALESCE(i.published_at, i.fetched_at) DESC
        LIMIT ?
        """,
        ((now - timedelta(days=days)).isoformat(timespec="seconds"), limit),
    )
    return [_shape_item(r, now) for r in rows]


def category_counts(db: Database, *, hours: int = 24) -> list[dict[str, Any]]:
    since = (utcnow() - timedelta(hours=hours)).isoformat(timespec="seconds")
    rows = db.query(
        """
        SELECT COALESCE(e.category, 'unclassified') AS category, COUNT(*) AS n
        FROM items i
        LEFT JOIN enrichment e ON e.item_id = i.id
        WHERE COALESCE(i.published_at, i.fetched_at) >= ?
        GROUP BY category
        ORDER BY n DESC
        """,
        (since,),
    )
    return [
        {
            "category": r["category"],
            "label": CATEGORY_LABELS.get(r["category"], r["category"].replace("-", " ").title()),
            "count": r["n"],
        }
        for r in rows
    ]


def source_health(db: Database) -> list[dict[str, Any]]:
    now = utcnow()
    rows = db.query(
        """
        SELECT s.*,
               (SELECT COUNT(*) FROM items i WHERE i.source_key = s.key) AS total_items,
               (SELECT COUNT(*) FROM items i WHERE i.source_key = s.key
                  AND COALESCE(i.published_at, i.fetched_at) >= datetime('now', '-7 days')) AS week_items
        FROM sources s
        WHERE s.enabled = 1 OR COALESCE(s.last_status, '') != 'retired'
        ORDER BY
            CASE s.last_status WHEN 'error' THEN 0 WHEN 'disabled' THEN 1 ELSE 2 END,
            s.name
        """
    )
    out = []
    for r in rows:
        out.append({
            "key": r["key"],
            "name": r["name"],
            "kind": r["kind"],
            "tier": r["tier"],
            "weight": r["weight"],
            "enabled": bool(r["enabled"]),
            "url": r["url"],
            "status": r["last_status"] or "never run",
            "error": r["last_error"] or "",
            "last_fetch": humanize_age(parse_datetime(r["last_fetch_at"]), now=now)
                          if r["last_fetch_at"] else "never",
            "last_new_items": r["last_new_items"],
            "consecutive_failures": r["consecutive_failures"],
            "total_items": r["total_items"],
            "week_items": r["week_items"],
        })
    return out


def recent_runs(db: Database, limit: int = 20) -> list[dict[str, Any]]:
    now = utcnow()
    rows = db.query(
        "SELECT id, started_at, finished_at, status, stats FROM runs ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    out = []
    for r in rows:
        stats = jload(r["stats"], {})
        ingest = stats.get("ingest") or {}
        out.append({
            "id": r["id"],
            "status": r["status"],
            "started": humanize_age(parse_datetime(r["started_at"]), now=now),
            "started_at": r["started_at"],
            "elapsed_s": stats.get("elapsed_s"),
            "new_items": ingest.get("new_items", 0),
            "sources_ok": ingest.get("ok", 0),
            "sources_failed": ingest.get("failed", 0),
            "enriched": (stats.get("enrich") or {}).get("enriched", 0),
            "clusters": (stats.get("cluster") or {}).get("clusters", 0),
            "errors": (ingest.get("errors") or [])[:8],
            "error": stats.get("error", ""),
        })
    return out


def dashboard_stats(db: Database) -> dict[str, Any]:
    now = utcnow()
    day = local_day(now)
    last_run = db.one("SELECT started_at, status FROM runs ORDER BY id DESC LIMIT 1")
    return {
        "items_24h": db.scalar(
            "SELECT COUNT(*) FROM items WHERE COALESCE(published_at, fetched_at) >= ?",
            ((now - timedelta(hours=24)).isoformat(timespec="seconds"),), default=0,
        ),
        "items_total": db.scalar("SELECT COUNT(*) FROM items", default=0),
        "stories_today": db.scalar("SELECT COUNT(*) FROM clusters WHERE day=?", (day,), default=0),
        "sources_ok": db.scalar(
            "SELECT COUNT(*) FROM sources WHERE enabled=1 AND last_status IN ('ok','not-modified')",
            default=0,
        ),
        "sources_total": db.scalar("SELECT COUNT(*) FROM sources WHERE enabled=1", default=0),
        "sources_failing": db.scalar(
            "SELECT COUNT(*) FROM sources WHERE enabled=1 AND last_status='error'", default=0,
        ),
        "saved": db.scalar("SELECT COUNT(*) FROM saved", default=0),
        "pending_enrich": db.scalar(
            "SELECT COUNT(*) FROM items WHERE id NOT IN (SELECT item_id FROM enrichment)",
            default=0,
        ),
        "judged": db.scalar("SELECT COUNT(*) FROM judgments", default=0),
        "adopt": db.scalar("SELECT COUNT(*) FROM judgments WHERE verdict='adopt'", default=0),
        "research_ready": db.scalar(
            "SELECT COUNT(*) FROM judgments WHERE verdict IN ('research','adopt')", default=0,
        ),
        "research_briefs": db.scalar(
            "SELECT COUNT(*) FROM research WHERE status='complete'", default=0,
        ),
        "last_run": humanize_age(parse_datetime(last_run["started_at"]), now=now) if last_run else "never",
        "last_run_status": last_run["status"] if last_run else "none",
    }


def get_brief(db: Database, day: str | None = None) -> dict[str, Any] | None:
    day = day or local_day()
    row = db.one("SELECT day, markdown, model, created_at FROM briefs WHERE day=?", (day,))
    if row is None:
        # Fall back to the most recent brief so the panel is never empty.
        row = db.one("SELECT day, markdown, model, created_at FROM briefs ORDER BY day DESC LIMIT 1")
    if row is None:
        return None
    return {
        "day": row["day"],
        "markdown": row["markdown"],
        "model": row["model"],
        "age": humanize_age(parse_datetime(row["created_at"])),
        "is_today": row["day"] == (day or local_day()),
    }


def source_options(db: Database) -> list[dict[str, str]]:
    rows = db.query(
        "SELECT key, name FROM sources WHERE enabled=1 ORDER BY name"
    )
    return [{"key": r["key"], "name": r["name"]} for r in rows]


def list_research(
    db: Database, *, verdict: str | None = None, limit: int = 40,
) -> list[dict[str, Any]]:
    now = utcnow()
    where = ["r.status = 'complete'"]
    params: list[Any] = []
    if verdict:
        where.append("r.verdict = ?")
        params.append(verdict)
    rows = db.query(
        f"""
        SELECT r.id, r.item_id, r.cluster_id, r.title, r.readiness, r.verdict,
               r.decision, r.model, r.created_at, r.updated_at,
               COALESCE(e.category, '') AS category,
               COALESCE(e.summary, '') AS summary,
               COALESCE(j.quality, 0) AS quality,
               COALESCE(j.practicality, 0) AS practicality,
               COALESCE(j.feasibility, 0) AS feasibility,
               COALESCE(j.usefulness, 0) AS usefulness,
               i.url
        FROM research r
        JOIN items i ON i.id = r.item_id
        LEFT JOIN enrichment e ON e.item_id = i.id
        LEFT JOIN judgments j ON j.item_id = i.id
        WHERE {' AND '.join(where)}
        ORDER BY r.readiness DESC, r.updated_at DESC
        LIMIT ?
        """,
        tuple(params + [limit]),
    )
    out = []
    for row in rows:
        out.append({
            "id": row["id"],
            "item_id": row["item_id"],
            "cluster_id": row["cluster_id"],
            "title": row["title"],
            "url": row["url"],
            "summary": row["summary"],
            "category": row["category"] or "opinion-analysis",
            "category_label": CATEGORY_LABELS.get(row["category"], "Other"),
            "readiness": round(float(row["readiness"] or 0), 2),
            "verdict": row["verdict"] or "",
            "decision": row["decision"] or "",
            "model": row["model"] or "",
            "quality": round(float(row["quality"] or 0), 2),
            "practicality": round(float(row["practicality"] or 0), 2),
            "feasibility": round(float(row["feasibility"] or 0), 2),
            "usefulness": round(float(row["usefulness"] or 0), 2),
            "age": humanize_age(parse_datetime(row["updated_at"]), now=now),
        })
    return out


def get_research(db: Database, research_id: int) -> dict[str, Any] | None:
    row = db.one(
        """
        SELECT r.id, r.item_id, r.cluster_id, r.title, r.readiness, r.verdict,
               r.decision, r.model, r.created_at, r.updated_at, r.status,
               COALESCE(e.category, '') AS category,
               COALESCE(e.summary, '') AS summary,
               COALESCE(j.quality, 0) AS quality,
               COALESCE(j.practicality, 0) AS practicality,
               COALESCE(j.feasibility, 0) AS feasibility,
               COALESCE(j.usefulness, 0) AS usefulness,
               COALESCE(j.reasons, '[]') AS reasons,
               COALESCE(j.artifacts, '[]') AS artifacts,
               i.url
        FROM research r
        JOIN items i ON i.id = r.item_id
        LEFT JOIN enrichment e ON e.item_id = i.id
        LEFT JOIN judgments j ON j.item_id = i.id
        WHERE r.id = ?
        """,
        (research_id,),
    )
    if row is None:
        return None
    pages = db.query(
        """
        SELECT slug, title, markdown, turn
        FROM research_pages
        WHERE research_id = ?
        ORDER BY turn ASC
        """,
        (research_id,),
    )
    return {
        "id": row["id"],
        "item_id": row["item_id"],
        "cluster_id": row["cluster_id"],
        "title": row["title"],
        "url": row["url"],
        "summary": row["summary"],
        "category": row["category"] or "opinion-analysis",
        "category_label": CATEGORY_LABELS.get(row["category"], "Other"),
        "status": row["status"],
        "readiness": round(float(row["readiness"] or 0), 2),
        "verdict": row["verdict"] or "",
        "decision": row["decision"] or "",
        "model": row["model"] or "",
        "quality": round(float(row["quality"] or 0), 2),
        "practicality": round(float(row["practicality"] or 0), 2),
        "feasibility": round(float(row["feasibility"] or 0), 2),
        "usefulness": round(float(row["usefulness"] or 0), 2),
        "reasons": jload(row["reasons"], []),
        "artifacts": jload(row["artifacts"], []),
        "age": humanize_age(parse_datetime(row["updated_at"])),
        "pages": [
            {"slug": p["slug"], "title": p["title"], "markdown": p["markdown"], "turn": p["turn"]}
            for p in pages
        ],
    }


def ready_briefs(db: Database, *, limit: int = 8) -> list[dict[str, Any]]:
    """Stories a practitioner should look at first — adopt, then spike."""
    return list_research(db, limit=limit)
