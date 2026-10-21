"""Live smoke test (marker `live`, spends tokens): one real gpt-6-luna agent with live web search.

Run with `uv run pytest -m live -s`. Global context: proves the full chain — flags, stdin prompt, strict
output schema together with web search, JSONL streaming, parsing — works against the real Codex backend.
"""

import json  # read raw events
from dataclasses import replace  # small per-test settings overrides
from datetime import date  # today's date for the prompt
from pathlib import Path  # temporary run folder

import pytest  # markers

from agentic_news.catalog import Job  # the smallest useful job
from agentic_news.codex_runner import run_agent  # real agent
from agentic_news.logging_setup import setup_logging  # full log, like a real run
from agentic_news.pipeline import prepare_agent_dirs  # same folder preparation as real runs
from agentic_news.settings import load_settings  # the user's .env
from agentic_news.store import StatusBoard  # live status

pytestmark = pytest.mark.live


def test_one_real_agent(tmp_path: Path) -> None:
    """1 topic x 1 cell: finishes, searched the web, returns valid http(s) items, logs prompt + answer."""
    settings = replace(load_settings(), items_per_cell=1, max_items_per_agent=3, agent_timeout_minutes=10)
    log_path = setup_logging(tmp_path / "logs", "live")
    job = Job(topic="AI industry", slug="ai-industry", intervals=("week",), types=("article",),
              sources=("viral_news",), variants=("pop_sci",))
    [spec] = prepare_agent_dirs([job], tmp_path / "run", "live", date.today(), settings)
    result = run_agent(spec, settings, StatusBoard(tmp_path / "run" / "status.json", "live", [job]))
    events = [json.loads(line) for f in spec.agent_dir.glob("events_attempt*.jsonl")
              for line in f.read_text(encoding="utf-8").splitlines()]
    assert result.state == "done", result.error
    assert any((e.get("item") or {}).get("type") == "web_search" for e in events)  # really searched
    assert result.items and all(r["url"].startswith(("http://", "https://")) for r in result.items)
    log_text = log_path.read_text(encoding="utf-8")
    assert "TOPIC: AI industry" in log_text and "final answer:" in log_text
