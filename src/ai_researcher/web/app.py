"""FastAPI application: the dashboard itself."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt

from ..config import CATEGORY_LABELS, Settings
from ..db import Database
from ..pipeline import Pipeline, sync_sources
from ..trends import rising_topics, top_entities
from ..util import iso, local_day, utcnow
from . import queries as Q

log = logging.getLogger("ai_researcher.web")

WEB_DIR = Path(__file__).resolve().parent
MD = MarkdownIt("commonmark", {"breaks": True, "linkify": True})


class RunState:
    """Guards against two ingest runs overlapping."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.running = False
        self.started_at: str = ""
        self.last_result: dict[str, Any] = {}

    @property
    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "started_at": self.started_at,
            "last_result": self.last_result,
        }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    db = Database(settings.db_path)
    pipeline = Pipeline(settings, db)
    sync_sources(db, pipeline.sources)
    state = RunState()

    auto_refresh_min = int(os.environ.get("AIR_AUTO_REFRESH_MIN", "0") or 0)

    async def _do_run(**kwargs) -> dict[str, Any]:
        if state.lock.locked():
            return {"status": "busy"}
        async with state.lock:
            state.running = True
            state.started_at = iso(utcnow())
            try:
                result = await asyncio.to_thread(_run_sync, pipeline, kwargs)
            finally:
                state.running = False
            state.last_result = result
            return result

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if auto_refresh_min > 0:
            async def loop():
                # First tick is delayed so startup stays fast and a restart
                # storm cannot hammer every source at once.
                await asyncio.sleep(30)
                while True:
                    try:
                        await _do_run()
                    except Exception:  # noqa: BLE001
                        log.exception("scheduled run failed")
                    await asyncio.sleep(auto_refresh_min * 60)
            task = asyncio.create_task(loop())
            log.info("in-process refresh enabled: every %s min", auto_refresh_min)
        yield
        if task:
            task.cancel()
        db.close()

    app = FastAPI(title="AI Researcher", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    templates.env.filters["markdown"] = lambda text: MD.render(text or "")
    templates.env.globals["CATEGORY_LABELS"] = CATEGORY_LABELS

    # ── optional access token ────────────────────────────────────────
    @app.middleware("http")
    async def guard(request: Request, call_next):
        if settings.access_token and not request.url.path.startswith("/static"):
            supplied = (
                request.query_params.get("k")
                or request.headers.get("X-AIR-Token")
                or request.cookies.get("air_token")
            )
            if supplied != settings.access_token:
                return HTMLResponse(
                    "<h1>401</h1><p>Append <code>?k=YOUR_TOKEN</code> to the URL.</p>",
                    status_code=401,
                )
            response = await call_next(request)
            # Remember the token so deep links inside the app keep working.
            response.set_cookie(
                "air_token", settings.access_token, max_age=90 * 86400,
                httponly=True, samesite="lax",
            )
            return response
        return await call_next(request)

    def ctx(request: Request, **extra) -> dict[str, Any]:
        base = {
            "request": request,
            "stats": Q.dashboard_stats(db),
            "run_state": state.status,
            "categories": [{"key": k, "label": v} for k, v in CATEGORY_LABELS.items()],
            "now": utcnow(),
        }
        base.update(extra)
        return base

    # ── pages ────────────────────────────────────────────────────────
    @app.get("/", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        day: str | None = Query(None),
        category: str | None = Query(None),
        min_sources: int = Query(0),
    ):
        target_day = day or local_day()
        stories = Q.top_stories(
            db, day=target_day, limit=40, category=category, min_sources=min_sources
        )
        # A fresh install has items but no clusters until the first analyse pass;
        # show the raw firehose rather than an empty page.
        fallback_items = [] if stories else Q.list_items(db, hours=48, limit=40, order="important")
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            ctx(
                request,
                page="dashboard",
                day=target_day,
                brief=Q.get_brief(db, target_day),
                stories=stories,
                fallback_items=fallback_items,
                rising=rising_topics(db, target_day, limit=14),
                entities=top_entities(db, days=2, limit=12),
                drops=Q.model_drops(db, days=7, limit=12),
                counts=Q.category_counts(db, hours=24),
                active_category=category,
                min_sources=min_sources,
            ),
        )

    @app.get("/feed", response_class=HTMLResponse)
    async def feed(
        request: Request,
        hours: int = Query(48),
        category: str | None = Query(None),
        source: str | None = Query(None),
        tier: str | None = Query(None),
        order: str = Query("recent"),
        page: int = Query(1, ge=1),
    ):
        per_page = 60
        items = Q.list_items(
            db, hours=hours, category=category, source_key=source, tier=tier,
            order=order, limit=per_page, offset=(page - 1) * per_page,
        )
        return templates.TemplateResponse(
            request,
            "feed.html",
            ctx(
                request, page="feed", items=items, hours=hours, order=order,
                active_category=category, active_source=source, active_tier=tier,
                sources=Q.source_options(db), page_num=page,
                has_more=len(items) == per_page,
            ),
        )

    @app.get("/search", response_class=HTMLResponse)
    async def search(request: Request, q: str = Query("")):
        items = Q.search_items(db, q, limit=120) if q.strip() else []
        return templates.TemplateResponse(
            request,
            "search.html",
            ctx(request, page="search", items=items, query=q,
                fts=db.fts_enabled),
        )

    @app.get("/saved", response_class=HTMLResponse)
    async def saved(request: Request):
        items = Q.list_items(db, hours=24 * 3650, saved_only=True, limit=300)
        return templates.TemplateResponse(
            request,
            "feed.html",
            ctx(request, page="saved", items=items, hours=0, order="recent",
                active_category=None, active_source=None, active_tier=None,
                sources=[], page_num=1, has_more=False, saved_view=True),
        )

    @app.get("/sources", response_class=HTMLResponse)
    async def sources(request: Request):
        return templates.TemplateResponse(
            request,
            "sources.html",
            ctx(request, page="sources", sources=Q.source_health(db)),
        )

    @app.get("/runs", response_class=HTMLResponse)
    async def runs(request: Request):
        return templates.TemplateResponse(
            request,
            "runs.html",
            ctx(request, page="runs", runs=Q.recent_runs(db, limit=30)),
        )

    # ── json api ─────────────────────────────────────────────────────
    @app.get("/api/status")
    async def api_status():
        return {"stats": Q.dashboard_stats(db), "run": state.status}

    @app.get("/api/stories")
    async def api_stories(day: str | None = None, limit: int = 40):
        return {"day": day or local_day(),
                "stories": Q.top_stories(db, day=day, limit=limit)}

    @app.get("/api/rising")
    async def api_rising(day: str | None = None):
        return {"rising": rising_topics(db, day, limit=25)}

    @app.post("/api/refresh")
    async def api_refresh(request: Request, background: bool = True):
        if state.running:
            return JSONResponse({"status": "busy"}, status_code=409)
        if background:
            asyncio.create_task(_do_run())
            return {"status": "started"}
        return await _do_run()

    @app.post("/api/save/{item_id}")
    async def api_save(item_id: int):
        exists = db.one("SELECT id FROM items WHERE id=?", (item_id,))
        if not exists:
            raise HTTPException(404, "no such item")
        row = db.one("SELECT item_id FROM saved WHERE item_id=?", (item_id,))
        if row:
            db.execute("DELETE FROM saved WHERE item_id=?", (item_id,))
            return {"saved": False}
        db.execute(
            "INSERT INTO saved (item_id, saved_at) VALUES (?,?)", (item_id, iso(utcnow()))
        )
        return {"saved": True}

    @app.post("/refresh")
    async def refresh_form(request: Request):
        if not state.running:
            asyncio.create_task(_do_run())
        referer = request.headers.get("referer", "/")
        return RedirectResponse(referer, status_code=303)

    return app


def _run_sync(pipeline: Pipeline, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Run the async pipeline on its own loop inside a worker thread.

    The pipeline opens SQLite connections, and those are thread-confined; running
    it in a thread keeps the web request loop responsive during a multi-minute
    ingest without sharing a connection across threads.
    """
    return asyncio.run(pipeline.run(**kwargs))
