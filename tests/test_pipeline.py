"""End-to-end tests of the pipeline wrapper through the CLI entry point, using fixtures/fake_codex.py.

Global context: this is the exact path the dashboard triggers (`python -m agentic_news.cli run --run-id ...`):
selection -> jobs -> agent folders -> parallel agents -> results.json/csv + status.json + run log.
"""

from pathlib import Path  # temporary project layout

from agentic_news.cli import main  # entry point under test
from agentic_news.store import read_json, write_json  # write selection, read outputs
from conftest import selection  # checked one-cell rows


def test_cli_run_produces_results_status_and_log(fake_env: Path) -> None:
    """Three checked topics (one failing) -> results from two agents, per-agent states, full log."""
    write_json(fake_env / "data" / "selection.json", selection("Physics", "Pure math", "MODE=fail topic"))
    assert main(["run", "--run-id", "t1"]) == 0
    run_dir = fake_env / "runs" / "t1"
    status = read_json(run_dir / "status.json")
    states = {slug: a["state"] for slug, a in status["agents"].items()}
    assert status["state"] == "done" and states == {"physics": "done", "pure-math": "done", "mode-fail-topic": "failed"}
    results = read_json(run_dir / "results.json")
    assert {r["topic"] for r in results} == {"Physics", "Pure math"} and (run_dir / "results.csv").exists()
    assert (run_dir / "selection.json").exists() and (run_dir / "physics" / "prompt.md").exists()
    log_text = (fake_env / "logs" / "run_t1.log").read_text(encoding="utf-8")
    assert "TOPIC: Physics" in log_text and "final answer:" in log_text  # full prompt + answer logged


def test_cli_without_selection_marks_run_failed(fake_env: Path) -> None:
    """No saved selection -> exit code 1 and a failed status the dashboard can show."""
    assert main(["run", "--run-id", "t2"]) == 1
    status = read_json(fake_env / "runs" / "t2" / "status.json")
    assert status["state"] == "failed" and "selection" in status["error"]
