"""Tests for store.py — atomic JSON files, results, run listing and the live status board.

Global context: the runner process writes status.json while the Streamlit dashboard reads it; on Windows
`os.replace` fails with PermissionError while another process has the target open, so writes retry.
"""

import json  # read files back
import os  # monkeypatch target os.replace
from pathlib import Path  # temporary run folders

import pytest  # monkeypatch fixture

from agentic_news import store  # module under test
from agentic_news.catalog import Job  # jobs registered on the status board

JOB = Job(topic="Physics", slug="physics", intervals=("day",), types=("paper",), sources=("viral_news",),
          variants=("rigorous",))


def test_write_json_retries_permission_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two PermissionErrors from os.replace are retried, then the write succeeds."""
    real_replace, calls = os.replace, []

    def flaky(src: str, dst: str) -> None:
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("file in use")  # what Windows raises while a reader holds the file
        real_replace(src, dst)

    monkeypatch.setattr(store.os, "replace", flaky)
    store.write_json(tmp_path / "a.json", {"x": "é"})
    assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8")) == {"x": "é"} and len(calls) == 3


def test_results_and_run_listing(tmp_path: Path) -> None:
    """Results round-trip through JSON (+ CSV export) and runs are listed newest first."""
    for rid in ("20261021-100000", "20261022-090000"):
        store.write_json(tmp_path / rid / "status.json", {"run_id": rid})
    store.write_json(tmp_path / "named" / "status.json", {"run_id": "named", "started": "2026-10-20T08:00:00"})
    rows = [{"topic": "Physics", "title": "T", "url": "https://x.org"}]
    store.save_results(tmp_path / "20261022-090000", rows)
    assert store.load_results(tmp_path / "20261022-090000") == rows
    assert (tmp_path / "20261022-090000" / "results.csv").exists()
    assert store.list_runs(tmp_path) == ["named", "20261022-090000", "20261021-100000"]  # start time first
    assert store.read_json(tmp_path / "missing.json", default=[]) == []  # missing file -> default


def test_status_board_tracks_agents(tmp_path: Path) -> None:
    """Board starts agents queued, applies events, forces writes on updates, and records the finish."""
    path = tmp_path / "status.json"
    board = store.StatusBoard(path, "r1", [JOB], min_interval=3600)  # throttle: only forced writes
    assert store.read_json(path)["agents"]["physics"]["state"] == "queued"
    board.apply("physics", {"type": "item.completed", "item": {"type": "web_search"}}, "web_search: q")
    board.update("physics", state="running")  # forced write includes the earlier applied event
    agent = store.read_json(path)["agents"]["physics"]
    assert agent["state"] == "running" and agent["searches"] == 1 and agent["last_event"] == "web_search: q"
    board.finish("done")
    status = store.read_json(path)
    assert status["state"] == "done" and status["ended"] and status["pid"] == os.getpid()
