"""Regression: live ingest progress tracking and persistence."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from ai_researcher.progress import RunProgress


@pytest.fixture
def progress_path(tmp_path: Path) -> Path:
    return tmp_path / "ingest.progress.json"


@pytest.fixture
def progress(progress_path: Path) -> RunProgress:
    return RunProgress(progress_path)


class TestRunProgressLifecycle:
    def test_starts_idle(self, progress: RunProgress):
        snap = progress.snapshot()
        assert snap["running"] is False
        assert snap["stage"] == "idle"
        assert snap["active"] == []

    def test_start_marks_running(self, progress: RunProgress):
        progress.start()
        snap = progress.snapshot()
        assert snap["running"] is True
        assert snap["stage"] == "starting"
        assert "Starting" in snap["detail"]

    def test_finish_preserves_counts_and_clears_active(self, progress: RunProgress):
        progress.begin_sources(3)
        progress.source_start("a", "Alpha")
        progress.source_done("a", "Alpha", status="ok", new_items=2)
        progress.finish(ok=True)
        snap = progress.snapshot()
        assert snap["running"] is False
        assert snap["stage"] == "done"
        assert snap["active"] == []
        assert snap["done"] == 1
        assert snap["total"] == 3
        assert "complete" in snap["detail"].lower()

    def test_finish_error(self, progress: RunProgress):
        progress.start()
        progress.finish(ok=False)
        snap = progress.snapshot()
        assert snap["running"] is False
        assert snap["stage"] == "error"
        assert "fail" in snap["detail"].lower()


class TestSourceTracking:
    def test_tracks_concurrent_sources(self, progress: RunProgress):
        progress.begin_sources(3)
        progress.source_start("a", "Alpha")
        progress.source_start("b", "Beta")
        snap = progress.snapshot()
        assert snap["stage"] == "ingest"
        assert snap["done"] == 0
        assert snap["total"] == 3
        assert snap["active"] == ["Alpha", "Beta"]
        assert "Alpha" in snap["detail"] and "Beta" in snap["detail"]

        progress.source_done("a", "Alpha", status="ok", new_items=5)
        snap = progress.snapshot()
        assert snap["done"] == 1
        assert snap["active"] == ["Beta"]
        assert "Alpha → ok" in snap["current"]
        assert "(+5)" in snap["current"]

        progress.source_done("b", "Beta", status="error", new_items=0)
        snap = progress.snapshot()
        assert snap["done"] == 2
        assert snap["active"] == []
        assert "2/3" in snap["detail"]

    def test_update_stage_detail(self, progress: RunProgress):
        progress.update(
            stage="enrich",
            detail="Model pass · 3/40",
            current="Some headline",
            done=3,
            total=40,
            active=[],
        )
        snap = progress.snapshot()
        assert snap["running"] is True
        assert snap["stage"] == "enrich"
        assert snap["done"] == 3
        assert snap["total"] == 40
        assert snap["current"] == "Some headline"


class TestSidecarPersistence:
    def test_persists_and_reloads(self, progress: RunProgress, progress_path: Path):
        progress.begin_sources(2)
        progress.source_start("x", "X Corp")
        assert progress_path.is_file()

        loaded = RunProgress.load(progress_path)
        assert loaded["running"] is True
        assert loaded["stage"] == "ingest"
        assert loaded["total"] == 2
        assert "X Corp" in loaded["active"]

    def test_load_missing_file_is_idle(self, tmp_path: Path):
        loaded = RunProgress.load(tmp_path / "nope.json")
        assert loaded["running"] is False
        assert loaded["stage"] == "idle"

    def test_load_corrupt_file_is_idle(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        loaded = RunProgress.load(path)
        assert loaded["running"] is False

    def test_stale_running_file_treated_as_idle(self, tmp_path: Path):
        path = tmp_path / "stale.json"
        path.write_text(
            json.dumps({
                "running": True,
                "stage": "ingest",
                "detail": "stuck",
                "current": "",
                "done": 1,
                "total": 10,
                "active": ["Reddit"],
                "updated_at": time.time() - (50 * 60),
            }),
            encoding="utf-8",
        )
        loaded = RunProgress.load(path)
        assert loaded["running"] is False
        assert loaded["stage"] == "idle"

    def test_atomic_write_readable_mid_update(self, progress: RunProgress, progress_path: Path):
        """Readers must never see a half-written sidecar."""
        errors: list[Exception] = []

        def reader():
            for _ in range(100):
                try:
                    data = json.loads(progress_path.read_text(encoding="utf-8"))
                    assert isinstance(data, dict)
                except FileNotFoundError:
                    pass
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                    return

        progress.start()
        t = threading.Thread(target=reader)
        t.start()
        for i in range(50):
            progress.update(stage="enrich", detail=f"tick {i}", done=i, total=50)
        t.join(timeout=5)
        assert not errors
