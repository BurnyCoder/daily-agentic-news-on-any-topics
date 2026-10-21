"""End-to-end tests of the pipeline wrapper through the CLI entry point, using fixtures/fake_codex.py.

Global context: this is the exact path the dashboard triggers (`python -m agentic_news.cli run --run-id ...`):
selection -> jobs -> agent folders -> parallel agents -> results.json/csv + status.json + run log.
"""

import sys  # interpreter for the fake codex
from pathlib import Path  # temporary project layout

import pytest  # monkeypatch fixture

from agentic_news.catalog import default_rows  # realistic selection rows
from agentic_news.cli import main  # entry point under test
from agentic_news.store import read_json, write_json  # write selection, read outputs

FAKE = Path(__file__).parent / "fixtures" / "fake_codex.py"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point settings at the fake codex and temporary runs/logs/data folders via environment overrides."""
    monkeypatch.setenv("CODEX_CMD", f"{sys.executable},{FAKE}")
    for key in ("RUNS_DIR", "LOGS_DIR", "DATA_DIR"):
        monkeypatch.setenv(key, str(tmp_path / key.split("_")[0].lower()))  # absolute paths win over root
    monkeypatch.setenv("MAX_PARALLEL_AGENTS", "2")
    monkeypatch.setenv("AGENT_MAX_RETRIES", "0")
    return tmp_path


def test_cli_run_produces_results_status_and_log(env: Path) -> None:
    """Three checked topics (one failing) -> results from two agents, per-agent states, full log."""
    rows = default_rows()[:4]
    for row, topic in zip(rows, ("Physics", "Pure math", "MODE=fail topic")):
        row.update(run=True, topic=topic, intervals=["day"], types=["paper"], sources=["viral_news"])
    write_json(env / "data" / "selection.json", rows)  # what the dashboard saves
    assert main(["run", "--run-id", "t1"]) == 0
    run_dir = env / "runs" / "t1"
    status = read_json(run_dir / "status.json")
    states = {slug: a["state"] for slug, a in status["agents"].items()}
    assert status["state"] == "done" and states == {"physics": "done", "pure-math": "done", "mode-fail-topic": "failed"}
    results = read_json(run_dir / "results.json")
    assert {r["topic"] for r in results} == {"Physics", "Pure math"} and (run_dir / "results.csv").exists()
    assert (run_dir / "selection.json").exists() and (run_dir / "physics" / "prompt.md").exists()
    log_text = (env / "logs" / "run_t1.log").read_text(encoding="utf-8")
    assert "TOPIC: Physics" in log_text and "final answer:" in log_text  # full prompt + answer logged


def test_cli_without_selection_marks_run_failed(env: Path) -> None:
    """No saved selection -> exit code 1 and a failed status the dashboard can show."""
    assert main(["run", "--run-id", "t2"]) == 1
    status = read_json(env / "runs" / "t2" / "status.json")
    assert status["state"] == "failed" and "selection" in status["error"]
