"""Shared pytest fixtures (https://docs.pytest.org/en/stable/reference/fixtures.html#conftest-py-sharing-fixtures-across-multiple-files).

Global context: `fake_env` makes load_settings() — in this process and in background CLI processes, which
inherit the environment — use fixtures/fake_codex.py and temporary runs/logs/data folders.
"""

import sys  # interpreter for the fake codex
from pathlib import Path  # temporary folders

import pytest  # fixtures

FAKE = Path(__file__).parent / "fixtures" / "fake_codex.py"


def selection(*topics: str) -> list[dict]:
    """Checked one-cell rows for the given topics (a topic containing MODE=<x> picks a fake behaviour)."""
    return [{"run": True, "topic": t, "intervals": ["day"], "types": ["paper"], "sources": ["viral_news"],
             "variants": ["rigorous"]} for t in topics]


@pytest.fixture
def fake_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Environment overrides -> fake codex, tmp folders, 2 parallel agents, no retries, 5 s timeout."""
    monkeypatch.setenv("CODEX_CMD", f"{sys.executable},{FAKE}")
    for key in ("RUNS_DIR", "LOGS_DIR", "DATA_DIR"):
        monkeypatch.setenv(key, str(tmp_path / key.split("_")[0].lower()))  # absolute paths win over root
    monkeypatch.setenv("MAX_PARALLEL_AGENTS", "2")
    monkeypatch.setenv("AGENT_MAX_RETRIES", "0")
    monkeypatch.setenv("AGENT_TIMEOUT_MINUTES", "0.1")
    return tmp_path
