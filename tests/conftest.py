"""Shared pytest fixtures (https://docs.pytest.org/en/stable/reference/fixtures.html#conftest-py-sharing-fixtures-across-multiple-files).

Global context: `fake_env` makes load_settings() — in this process and in background CLI processes, which
inherit the environment — use fixtures/fake_codex.py and temporary runs/logs/data folders; `make_config`
builds small RunConfigs (a few cells) so no test needs the full cell space.
"""

import sys  # interpreter for the fake codex
from dataclasses import replace  # custom topic entries
from pathlib import Path  # temporary folders

import pytest  # fixtures

from agentic_news.catalog import Option, default_dimensions, slugify  # cell space
from agentic_news.config import RunConfig  # what the pipeline runs

FAKE = Path(__file__).parent / "fixtures" / "fake_codex.py"
PER_TOPIC = ["interval", "type", "source", "variant"]  # merge everything but topic -> one agent per topic


def make_config(*topics: str, intervals: tuple[str, ...] = ("day",), merge: list[str] = PER_TOPIC,
                **extra: object) -> RunConfig:
    """Topic entries named after `topics` (a label containing MODE=<x> picks a fake behaviour), one checked rule
    per topic with one type/source/variant and the given intervals."""
    dims = default_dimensions()
    dims[0] = replace(dims[0], options=tuple(Option(slugify(t), t) for t in topics))
    rules = [{"run": True, "topic": [slugify(t)], "interval": list(intervals), "type": ["paper"],
              "source": ["viral_news"], "variant": ["rigorous"]} for t in topics]
    return RunConfig(dimensions=dims, rules=rules, merge=merge, **extra)


@pytest.fixture
def fake_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Environment overrides -> fake codex, tmp folders, 2 parallel agents, no retries, 6 s timeout."""
    monkeypatch.setenv("CODEX_CMD", f"{sys.executable},{FAKE}")
    for key in ("RUNS_DIR", "LOGS_DIR", "DATA_DIR"):
        monkeypatch.setenv(key, str(tmp_path / key.split("_")[0].lower()))  # absolute paths win over root
    monkeypatch.setenv("MAX_PARALLEL_AGENTS", "2")
    monkeypatch.setenv("AGENT_MAX_RETRIES", "0")
    monkeypatch.setenv("AGENT_TIMEOUT_MINUTES", "0.1")
    return tmp_path
