"""Thread-safe live progress for an ingest run.

The pipeline updates this from a worker thread; the web UI reads snapshots via
`/api/status`. A JSON sidecar in the data dir lets a dashboard see CLI/systemd
runs too, without sharing memory.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any


class RunProgress:
    def __init__(self, path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._path = path
        self._state: dict[str, Any] = self._idle()

    @staticmethod
    def _idle() -> dict[str, Any]:
        return {
            "running": False,
            "stage": "idle",
            "detail": "",
            "current": "",
            "done": 0,
            "total": 0,
            "active": [],
            "updated_at": 0.0,
        }

    def start(self) -> None:
        with self._lock:
            self._state = {
                "running": True,
                "stage": "starting",
                "detail": "Starting ingest run",
                "current": "",
                "done": 0,
                "total": 0,
                "active": [],
                "updated_at": time.time(),
            }
            self._persist()

    def finish(self, *, ok: bool = True) -> None:
        with self._lock:
            self._state = {
                "running": False,
                "stage": "done" if ok else "error",
                "detail": "Refresh complete" if ok else "Refresh failed",
                "current": "",
                "done": self._state.get("done", 0),
                "total": self._state.get("total", 0),
                "active": [],
                "updated_at": time.time(),
            }
            self._persist()

    def clear(self) -> None:
        with self._lock:
            self._state = self._idle()
            self._persist()

    def update(
        self,
        *,
        stage: str | None = None,
        detail: str | None = None,
        current: str | None = None,
        done: int | None = None,
        total: int | None = None,
        active: list[str] | None = None,
    ) -> None:
        with self._lock:
            if stage is not None:
                self._state["stage"] = stage
            if detail is not None:
                self._state["detail"] = detail
            if current is not None:
                self._state["current"] = current
            if done is not None:
                self._state["done"] = done
            if total is not None:
                self._state["total"] = total
            if active is not None:
                self._state["active"] = list(active)
            self._state["running"] = True
            self._state["updated_at"] = time.time()
            self._persist()

    def begin_sources(self, total: int) -> None:
        self.update(
            stage="ingest",
            detail=f"Fetching sources · 0/{total}",
            current="",
            done=0,
            total=total,
            active=[],
        )

    def source_start(self, key: str, name: str) -> None:
        with self._lock:
            active = list(self._state.get("active") or [])
            label = name or key
            if label not in active:
                active.append(label)
            self._state["active"] = active
            self._state["stage"] = "ingest"
            self._state["current"] = label
            self._state["detail"] = self._ingest_detail(active)
            self._state["running"] = True
            self._state["updated_at"] = time.time()
            self._persist()

    def source_done(self, key: str, name: str, *, status: str, new_items: int) -> None:
        with self._lock:
            active = [a for a in (self._state.get("active") or []) if a != (name or key)]
            done = int(self._state.get("done") or 0) + 1
            total = int(self._state.get("total") or 0)
            self._state["active"] = active
            self._state["done"] = done
            self._state["stage"] = "ingest"
            self._state["current"] = f"{name or key} → {status}" + (
                f" (+{new_items})" if new_items else ""
            )
            self._state["detail"] = self._ingest_detail(active, done=done, total=total)
            self._state["running"] = True
            self._state["updated_at"] = time.time()
            self._persist()

    def _ingest_detail(
        self, active: list[str], *, done: int | None = None, total: int | None = None
    ) -> str:
        done = self._state.get("done", 0) if done is None else done
        total = self._state.get("total", 0) if total is None else total
        if active:
            shown = ", ".join(active[:3])
            extra = len(active) - 3
            if extra > 0:
                shown += f" (+{extra} more)"
            return f"Fetching · {shown} · {done}/{total} done"
        return f"Fetching sources · {done}/{total} done"

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _persist(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self._state, separators=(",", ":"))
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, self._path)
        except OSError:
            pass

    @classmethod
    def load(cls, path: Path) -> dict[str, Any]:
        """Read a progress sidecar written by any process."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                out = cls._idle()
                out.update({k: data[k] for k in out if k in data})
                # Stale file from a crashed run: treat as idle after 45 min.
                age = time.time() - float(out.get("updated_at") or 0)
                if out.get("running") and age > 45 * 60:
                    out["running"] = False
                    out["stage"] = "idle"
                    out["detail"] = ""
                return out
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
        return cls._idle()
