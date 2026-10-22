"""Live smoke tests (marker `live`, spend tokens): real gpt-6-luna agents with live web search on 2 cells only.

Run with `uv run pytest -m live -s`. Global context: proves the full chain — granular cells, user-chosen batching,
flags, stdin prompt, strict output schema with web search, JSONL streaming, parsing into the right cells —
against the real Codex backend, using the smallest grid that distinguishes split from merged batching
(1 topic x 2 intervals x 1 type x 1 source x 1 variant = 2 cells): 3 short agent runs in total.
"""

import json  # read raw events
from dataclasses import replace  # per-test settings
from pathlib import Path  # temporary run folders

import pytest  # markers + parametrize

from agentic_news.catalog import default_dimensions  # built-in dimensions
from agentic_news.config import RunConfig  # what to run
from agentic_news.logging_setup import setup_logging  # full log, like a real run
from agentic_news.pipeline import run_pipeline  # the real wrapper
from agentic_news.settings import load_settings  # the user's .env
from agentic_news.store import read_json, write_json  # config in, results out
from agentic_news.config import config_to_dict  # config file

pytestmark = pytest.mark.live
RULE = {"run": True, "topic": ["ai-industry"], "interval": ["day", "week"], "type": ["article"],
        "source": ["viral_news"], "variant": ["pop_sci"]}


@pytest.mark.parametrize(("merge", "agents"), [([], 2), (["interval"], 1)])
def test_two_cells_split_or_merged(tmp_path: Path, merge: list[str], agents: int) -> None:
    """Each agent finishes, searched the web, and every item lands in one of the 2 selected cells."""
    settings = replace(load_settings(), runs_dir=tmp_path / "runs", logs_dir=tmp_path / "logs", agent_timeout_minutes=10)
    log_path = setup_logging(settings.logs_dir, "live")
    cfg = RunConfig(default_dimensions(), [RULE], merge=merge, overrides={"items_per_cell": 1})
    write_json(tmp_path / "config.json", config_to_dict(cfg))
    run_dir = run_pipeline("live", settings, tmp_path / "config.json")
    status, results = read_json(run_dir / "status.json"), read_json(run_dir / "results.json")
    assert len(status["agents"]) == agents and all(a["state"] == "done" for a in status["agents"].values())
    events = [json.loads(line) for f in run_dir.glob("*/events_attempt*.jsonl")
              for line in f.read_text(encoding="utf-8").splitlines()]
    assert any((e.get("item") or {}).get("type") == "web_search" for e in events)  # really searched
    assert results and {(r["topic"], r["interval"]) for r in results} <= {("ai-industry", "day"), ("ai-industry", "week")}
    assert all(r["url"].startswith(("http://", "https://")) for r in results)
    assert "final answer:" in log_path.read_text(encoding="utf-8")
