"""Storage: every file the app reads or writes — run folders, status, results and the saved workspace.

Local: JSON is written atomically (temp file + `os.replace`, https://docs.python.org/3/library/os.html#os.replace).
On Windows `os.replace` raises PermissionError while another process holds the target open (the dashboard
polling status.json; https://github.com/python/cpython/issues/90161), so writes retry briefly. StatusBoard is
the single writer of status.json for a run.
Global context: layout is runs/<run_id>/{config.json, status.json, results.json, results.csv, <agent>/...}
and data/workspace.json; the CLI writes run files, the Streamlit dashboard reads them and edits the workspace.
"""

import json  # file format
import os  # atomic replace + current pid
import threading  # StatusBoard is shared by the runner's worker threads
import time  # retry backoff and write throttling
from datetime import datetime  # run ids and timestamps
from pathlib import Path  # paths

import pandas as pd  # CSV export of results

from agentic_news.catalog import Job  # agents registered on the board
from agentic_news.events import apply_event, new_counters  # per-event counter updates

def now() -> str:
    """Local timestamp, second precision, ISO 8601."""
    return datetime.now().isoformat(timespec="seconds")


def new_run_id() -> str:
    """Sortable timestamp id, e.g. 20261022-091500."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def write_json(path: Path, data: object, attempts: int = 8) -> None:
    """Atomically write JSON, retrying PermissionError while a reader holds the file (Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for attempt in range(attempts):
        try:
            os.replace(tmp, path)  # atomic swap: readers see the old or the new file, never half of one
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.05 * (attempt + 1))  # short linear backoff


def read_json(path: Path, default: object = None) -> object:
    """Parsed JSON, or `default` if the file is missing or mid-write/corrupt."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_results(run_dir: Path, rows: list[dict], columns: list[str]) -> None:
    """results.json (source of truth) + results.csv (for spreadsheets) with the given column order."""
    write_json(run_dir / "results.json", rows)
    pd.DataFrame(rows, columns=columns).to_csv(run_dir / "results.csv", index=False, encoding="utf-8")


def load_results(run_dir: Path) -> list[dict]:
    """Rows saved by save_results; while a run is still going, the items.json of agents already done."""
    if (run_dir / "results.json").exists():
        return read_json(run_dir / "results.json", default=[])
    return [row for path in sorted(run_dir.glob("*/items.json")) for row in read_json(path, default=[])]


def list_runs(runs_dir: Path) -> list[str]:
    """Run ids that have a status file, newest first (by start time, then name; custom --run-id names allowed)."""
    if not runs_dir.exists():
        return []
    runs = [p for p in runs_dir.iterdir() if (p / "status.json").exists()]
    started = {p.name: (read_json(p / "status.json", default={}) or {}).get("started") or "" for p in runs}
    return sorted(started, key=lambda name: (started[name], name), reverse=True)


class StatusBoard:
    """Thread-safe live status of one run, mirrored to status.json for the dashboard."""

    def __init__(self, path: Path, run_id: str, jobs: list[Job], min_interval: float = 1.0) -> None:
        self._path, self._min_interval = path, min_interval  # throttle event-driven writes to ~1/s
        self._lock = threading.Lock()  # worker threads update concurrently
        self._last_write = 0.0
        self.data = {"run_id": run_id, "state": "running", "pid": os.getpid(), "started": now(), "ended": None,
                     "agents": {j.slug: {"label": j.label, "cells": len(j.cells), "state": "queued", "attempt": 0,
                                         "started": None, "ended": None, "items": 0, "dropped": 0, "last_event": "",
                                         **new_counters()} for j in jobs}}
        self._write()

    def _write(self) -> None:
        write_json(self._path, self.data)
        self._last_write = time.monotonic()

    def update(self, slug: str, **fields: object) -> None:
        """Set fields of one agent (state changes) and write immediately."""
        with self._lock:
            self.data["agents"][slug].update(fields)
            self._write()

    def apply(self, slug: str, event: dict, summary: str | None) -> None:
        """Count one Codex event; write at most every `min_interval` seconds."""
        with self._lock:
            agent = self.data["agents"][slug]
            apply_event(agent, event)
            if summary:
                agent["last_event"] = summary.strip().splitlines()[0][:200]  # short tail for the UI only
            if time.monotonic() - self._last_write >= self._min_interval:
                self._write()

    def finish(self, state: str) -> None:
        """Mark the whole run finished (done/failed)."""
        with self._lock:
            self.data.update(state=state, ended=now())
            self._write()
