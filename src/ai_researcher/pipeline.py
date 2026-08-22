"""The ingest pipeline: fetch → store → enrich → embed → cluster → brief.

One `run()` is a complete refresh. It is safe to call concurrently-ish (the web
UI guards with a lock) and safe to interrupt: every stage commits as it goes, so
a killed run leaves the database consistent, just less current.
"""

from __future__ import annotations

import asyncio
import errno
import fcntl
import logging
import os
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

from .config import Settings, Source, load_sources
from .connectors import build_registry
from .db import Database, jdump
from .enrich import Embedder, Enricher, OllamaClient
from .http import Fetcher
from .trends import build_clusters, compute_daily_topics, generate_brief
from .util import iso, utcnow

log = logging.getLogger("ai_researcher.pipeline")


class RunLockBusy(RuntimeError):
    """Another ingest run already holds the lock."""


@contextmanager
def run_lock(data_dir: Path):
    """Exclusive, cross-process ingest lock.

    Two concurrent runs are not merely wasteful: both drive Ollama at once, and
    under that contention the embedding endpoint was observed returning one
    batch's vectors for unrelated inputs, silently corrupting the index that
    clustering depends on. The systemd timer can easily fire while a manual run
    or a dashboard-triggered refresh is in flight, so the guard is a real file
    lock rather than an in-process one.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "ingest.lock"
    handle = open(path, "w")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise RunLockBusy(
                    f"another ingest run is already active (lock: {path})"
                ) from exc
            raise
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


def sync_sources(db: Database, sources: list[Source]) -> None:
    """Mirror the YAML catalog into the DB, preserving per-source fetch state."""
    with db.tx() as conn:
        for src in sources:
            conn.execute(
                """
                INSERT INTO sources (key, name, kind, tier, weight, enabled, url)
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                    name=excluded.name, kind=excluded.kind, tier=excluded.tier,
                    weight=excluded.weight, enabled=excluded.enabled, url=excluded.url
                """,
                (src.key, src.name, src.kind, src.tier, src.weight,
                 1 if src.enabled else 0, src.url),
            )
        # A source deleted from YAML stops being fetched but keeps its items.
        # It is marked 'retired' rather than left holding its last error, which
        # would otherwise show up forever as a failing source.
        keys = {s.key for s in sources}
        for row in conn.execute("SELECT key FROM sources").fetchall():
            if row["key"] not in keys:
                conn.execute(
                    "UPDATE sources SET enabled=0, last_status='retired', "
                    "last_error='', consecutive_failures=0 WHERE key=?",
                    (row["key"],),
                )


class Pipeline:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.sources = load_sources(settings)

    # ── stage 1: ingest ──────────────────────────────────────────────
    async def ingest(self, only: list[str] | None = None) -> dict[str, Any]:
        sync_sources(self.db, self.sources)
        targets = [s for s in self.sources if s.enabled and (not only or s.key in only)]

        fetcher = Fetcher(
            self.settings.user_agent,
            concurrency=self.settings.fetch_concurrency,
        )
        registry = build_registry(self.settings, fetcher)
        try:
            results = await asyncio.gather(
                *(self._ingest_source(src, registry) for src in targets),
                return_exceptions=True,
            )
        finally:
            await fetcher.aclose()

        stats = {"sources": len(targets), "new_items": 0, "ok": 0, "failed": 0,
                 "skipped": 0, "errors": []}
        for src, result in zip(targets, results):
            if isinstance(result, BaseException):
                stats["failed"] += 1
                stats["errors"].append(f"{src.key}: {type(result).__name__}: {result}")
                self._record_source_status(src.key, "error", str(result)[:300], 0)
                continue
            stats["new_items"] += result["new"]
            if result["status"] == "ok":
                stats["ok"] += 1
            elif result["status"] in ("disabled", "not-modified"):
                stats["skipped"] += 1
            else:
                stats["failed"] += 1
                if result.get("error"):
                    stats["errors"].append(f"{src.key}: {result['error']}")
        return stats

    async def _ingest_source(self, src: Source, registry) -> dict[str, Any]:
        connector = registry.get(src.kind)
        if connector is None:
            self._record_source_status(src.key, "error", f"unknown kind '{src.kind}'", 0)
            return {"status": "error", "new": 0, "error": f"unknown kind '{src.kind}'"}

        ok, reason = connector.available(src)
        if not ok:
            self._record_source_status(src.key, "disabled", reason, 0)
            return {"status": "disabled", "new": 0, "error": reason}

        row = self.db.one("SELECT etag, last_modified FROM sources WHERE key=?", (src.key,))
        state = {
            "etag": row["etag"] if row else "",
            "last_modified": row["last_modified"] if row else "",
            # Rotation position for connectors that cannot sweep every target
            # in one run (Reddit's rate limit forces this).
            "cursor": self.db.get_kv(f"cursor:{src.key}"),
        }

        started = time.monotonic()
        try:
            result = await connector.fetch(src, state)
        except Exception as exc:  # noqa: BLE001 - a broken feed must not sink the run
            log.warning("source %s raised: %s", src.key, exc)
            self._record_source_status(src.key, "error", f"{type(exc).__name__}: {exc}"[:300], 0)
            return {"status": "error", "new": 0, "error": str(exc)[:200]}

        if result.status == "error":
            if result.cursor:
                self.db.set_kv(f"cursor:{src.key}", result.cursor)
            self._record_source_status(src.key, "error", result.error, 0)
            return {"status": "error", "new": 0, "error": result.error}

        if result.cursor:
            self.db.set_kv(f"cursor:{src.key}", result.cursor)

        new_count = self._store(src, result.items) if result.items else 0
        self._record_source_status(
            src.key, result.status, result.error, new_count,
            etag=result.etag, last_modified=result.last_modified,
        )
        log.info(
            "%-18s %-14s %3d new / %3d fetched  (%.1fs)",
            src.key, result.status, new_count, len(result.items), time.monotonic() - started,
        )
        return {"status": result.status, "new": new_count, "error": result.error}

    def _store(self, src: Source, items) -> int:
        horizon = utcnow() - timedelta(days=self.settings.item_max_age_days)
        now_iso = iso(utcnow())
        new_count = 0

        with self.db.tx() as conn:
            for item in items:
                # A title is what the dashboard actually renders. An item
                # without one is unreadable in every view and unrankable by the
                # classifier, so it is dropped rather than shown as "(untitled)".
                if not item.title.strip() or not item.url:
                    continue
                published = item.published_at
                # Undated items are treated as "now" rather than dropped; feeds
                # that omit dates are common and usually still current.
                if published and published < horizon:
                    continue
                existing = conn.execute(
                    "SELECT id FROM items WHERE source_key=? AND external_id=?",
                    (src.key, item.external_id),
                ).fetchone()

                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO items (source_key, external_id, url, canonical_url,
                                           url_hash, content_hash, title, author, body,
                                           published_at, fetched_at, engagement, comments, meta)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            src.key, item.external_id, item.url, item.url, item.uhash,
                            item.chash, item.title, item.author, item.body,
                            iso(published) if published else None, now_iso,
                            item.engagement, item.comments, jdump(item.meta),
                        ),
                    )
                    new_count += 1
                else:
                    # Re-seeing an item is normal; only its engagement moves, and
                    # only upward — a cached listing must not erase a real count.
                    conn.execute(
                        "UPDATE items SET engagement=MAX(engagement, ?), "
                        "comments=MAX(comments, ?) WHERE id=?",
                        (item.engagement, item.comments, existing["id"]),
                    )
        return new_count

    def _record_source_status(
        self, key: str, status: str, error: str, new_items: int,
        *, etag: str = "", last_modified: str = "",
    ) -> None:
        failed = status == "error"
        self.db.execute(
            """
            UPDATE sources SET
                last_fetch_at = ?,
                last_status = ?,
                last_error = ?,
                last_new_items = ?,
                etag = CASE WHEN ? != '' THEN ? ELSE etag END,
                last_modified = CASE WHEN ? != '' THEN ? ELSE last_modified END,
                consecutive_failures = CASE WHEN ? THEN consecutive_failures + 1 ELSE 0 END
            WHERE key = ?
            """,
            (iso(utcnow()), status, error[:500], new_items,
             etag, etag, last_modified, last_modified, 1 if failed else 0, key),
        )

    # ── stage 2+: analysis ───────────────────────────────────────────
    async def analyse(self, *, brief: bool = True, force_brief: bool = False) -> dict[str, Any]:
        client = OllamaClient(self.settings)
        try:
            await client.probe()
            enrich_stats = await Enricher(self.settings, self.db, client).run()
            embed_stats = await Embedder(self.db, client).run()
            cluster_stats = build_clusters(self.db)
            topic_stats = compute_daily_topics(self.db)
            brief_stats = (
                await generate_brief(self.db, client, force=force_brief) if brief else {}
            )
        finally:
            await client.aclose()

        return {
            "enrich": enrich_stats,
            "embed": embed_stats,
            "cluster": cluster_stats,
            "topics": topic_stats,
            "brief": brief_stats,
            "ollama": {
                "available": client.available,
                "chat_model": client.chat_model,
                "embed_model": client.embed_model,
                "error": client.last_error,
            },
        }

    # ── full run ─────────────────────────────────────────────────────
    async def run(
        self, *, only: list[str] | None = None, skip_ingest: bool = False,
        force_brief: bool = False,
    ) -> dict[str, Any]:
        try:
            with run_lock(self.settings.data_dir):
                return await self._run(
                    only=only, skip_ingest=skip_ingest, force_brief=force_brief
                )
        except RunLockBusy as exc:
            log.warning("%s", exc)
            return {"status": "busy", "error": str(exc)}

    async def _run(
        self, *, only: list[str] | None = None, skip_ingest: bool = False,
        force_brief: bool = False,
    ) -> dict[str, Any]:
        started = utcnow()
        cur = self.db.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')", (iso(started),)
        )
        run_id = cur.lastrowid

        stats: dict[str, Any] = {}
        status = "ok"
        try:
            stats["ingest"] = {} if skip_ingest else await self.ingest(only=only)
            stats.update(await self.analyse(force_brief=force_brief))
            self.prune()
        except Exception as exc:  # noqa: BLE001 - record the failure, don't hide it
            status = "error"
            stats["error"] = f"{type(exc).__name__}: {exc}"
            log.exception("run failed")
        finally:
            elapsed = (utcnow() - started).total_seconds()
            stats["elapsed_s"] = round(elapsed, 1)
            self.db.execute(
                "UPDATE runs SET finished_at=?, status=?, stats=? WHERE id=?",
                (iso(utcnow()), status, jdump(stats), run_id),
            )
        stats["run_id"] = run_id
        stats["status"] = status
        return stats

    def prune(self) -> int:
        """Drop items past the retention horizon, keeping anything starred.

        Deletes are chunked: a first prune after a long outage can match tens of
        thousands of rows, and SQLite caps the number of bound parameters in a
        single statement.
        """
        cutoff = iso(utcnow() - timedelta(days=self.settings.retention_days))
        with self.db.tx() as conn:
            ids = [
                r["id"] for r in conn.execute(
                    "SELECT id FROM items WHERE COALESCE(published_at, fetched_at) < ? "
                    "AND id NOT IN (SELECT item_id FROM saved)",
                    (cutoff,),
                ).fetchall()
            ]
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                placeholders = ",".join("?" * len(chunk))
                # enrichment, embeddings and cluster_items cascade from here.
                conn.execute(f"DELETE FROM items WHERE id IN ({placeholders})", tuple(chunk))
                if self.db.fts_enabled:
                    conn.executemany(
                        "DELETE FROM items_fts WHERE rowid=?", [(i,) for i in chunk]
                    )
            conn.execute(
                "DELETE FROM runs WHERE id NOT IN "
                "(SELECT id FROM runs ORDER BY id DESC LIMIT 200)"
            )
        if ids:
            log.info("pruned %s items older than %s days", len(ids), self.settings.retention_days)
        return len(ids)
