"""Regression: dashboard status API and verbose-ingest UI wiring."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_researcher.config import Settings
from ai_researcher.progress import RunProgress
from ai_researcher.web.app import create_app


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated data dir so tests never touch the live dashboard DB."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("AIR_DATA_DIR", str(data))
    monkeypatch.setenv("AIR_ACCESS_TOKEN", "")
    monkeypatch.setenv("AIR_AUTO_REFRESH_MIN", "0")
    settings = Settings(
        data_dir=data,
        access_token="",
        sources_path=Path(__file__).resolve().parents[1] / "config" / "sources.yaml",
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    app = create_app(settings)
    return app, settings


@pytest.fixture
def client(app_env):
    app, _ = app_env
    with TestClient(app) as c:
        yield c


class TestStatusApi:
    def test_status_includes_progress_shape(self, client: TestClient):
        r = client.get("/api/status")
        assert r.status_code == 200
        body = r.json()
        assert "stats" in body and "run" in body
        run = body["run"]
        assert "running" in run
        assert "progress" in run
        progress = run["progress"]
        for key in ("running", "stage", "detail", "current", "done", "total", "active", "updated_at"):
            assert key in progress, f"missing progress.{key}"
        assert isinstance(progress["active"], list)
        assert progress["running"] is False
        assert progress["stage"] in ("idle", "done", "error")

    def test_status_stats_keys(self, client: TestClient):
        stats = client.get("/api/status").json()["stats"]
        for key in (
            "items_24h", "stories_today", "sources_ok", "sources_total",
            "sources_failing", "last_run", "last_run_status",
        ):
            assert key in stats

    def test_status_reflects_live_progress(self, client: TestClient, app_env):
        _, settings = app_env
        progress = RunProgress(settings.data_dir / "ingest.progress.json")
        # The app holds its own RunProgress instance; write the sidecar and
        # also poke the in-memory object via the module-level factory path by
        # updating through the shared file + ensuring disk fallback works when
        # the in-process flag is idle.
        progress.start()
        progress.begin_sources(4)
        progress.source_start("openai", "OpenAI")
        progress.update(
            stage="ingest",
            detail="Fetching · OpenAI · 0/4 done",
            current="OpenAI",
            done=0,
            total=4,
            active=["OpenAI"],
        )

        body = client.get("/api/status").json()
        # Disk sidecar is consulted when the web process is not itself running
        # an ingest; that is the CLI/systemd visibility path.
        p = body["run"]["progress"]
        assert p["running"] is True
        assert p["stage"] == "ingest"
        assert p["total"] == 4
        assert "OpenAI" in (p.get("detail") or "") or "OpenAI" in (p.get("active") or [])


class TestDashboardChrome:
    def test_home_includes_verbose_toggle(self, client: TestClient):
        html = client.get("/").text
        assert 'id="verbose-ingest"' in html
        assert "Show verbose ingest status" in html
        assert 'id="ingest-status"' in html
        assert 'id="ingest-stage"' in html
        assert 'id="ingest-detail"' in html
        assert 'id="ingest-current"' in html
        assert 'id="ingest-counts"' in html
        assert 'id="refresh"' in html
        assert 'id="statusdot"' in html
        assert 'data-stat="items_24h"' in html
        assert 'data-stat="stories_today"' in html
        assert 'data-stat="sources_ok"' in html

    def test_app_js_wires_verbose_polling(self, client: TestClient):
        js = client.get("/static/app.js").text
        assert "air.verboseIngest" in js
        assert "renderProgress" in js
        assert "/api/status" in js
        assert "/api/refresh" in js
        assert "verbose-ingest" in js
        assert "ingest-status" in js

    def test_app_css_defines_toggle_and_strip(self, client: TestClient):
        css = client.get("/static/app.css").text
        assert ".verbose-toggle" in css
        assert ".ingest-status" in css
        assert ".ingest-stage" in css
        assert ".ingest-status.live" in css

    def test_pages_render(self, client: TestClient):
        for path in ("/", "/feed", "/search", "/saved", "/sources", "/runs"):
            r = client.get(path)
            assert r.status_code == 200, path
            assert "AI" in r.text


class TestRefreshEndpoint:
    def test_refresh_starts_without_real_ingest(self, client: TestClient, monkeypatch):
        import ai_researcher.web.app as app_mod

        # Never run the real pipeline in unit tests — it hits the network.
        monkeypatch.setattr(
            app_mod, "_run_sync", lambda pipeline, kwargs: {"status": "ok", "elapsed_s": 0.01}
        )
        r = client.post("/api/refresh")
        assert r.status_code == 200
        assert r.json()["status"] == "started"

        # A second overlapping start should be rejected while the first holds
        # the in-process lock briefly; if it already finished, started is fine.
        r2 = client.post("/api/refresh")
        assert r2.status_code in (200, 409)
