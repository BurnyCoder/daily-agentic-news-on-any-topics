"""End-to-end tests of the pipeline wrapper through the CLI entry point, using fixtures/fake_codex.py.

Global context: this is the exact path the dashboard triggers (`python -m agentic_news.cli run --run-id ...`):
config -> granular cells -> agent batches -> agent folders -> parallel agents -> results + status + run log.
"""

from pathlib import Path  # temporary project layout

from agentic_news.cli import main  # entry point under test
from agentic_news.config import config_to_dict  # write workspace files
from agentic_news.store import read_json, write_json  # write config, read outputs
from conftest import make_config  # small configs


def _run(fake_env: Path, run_id: str, cfg) -> Path:
    write_json(fake_env / "data" / "workspace.json", config_to_dict(cfg))  # what the dashboard saves
    assert main(["run", "--run-id", run_id]) == 0
    return fake_env / "runs" / run_id


def test_cli_run_produces_results_status_and_log(fake_env: Path) -> None:
    """Three per-topic agents (one failing) -> results from two, per-agent states, full log, config snapshot."""
    run_dir = _run(fake_env, "t1", make_config("Physics", "Pure math", "MODE=fail topic"))
    status = read_json(run_dir / "status.json")
    states = {slug: a["state"] for slug, a in status["agents"].items()}
    assert status["state"] == "done" and states == {"physics": "done", "pure-math": "done", "mode-fail-topic": "failed"}
    results = read_json(run_dir / "results.json")
    assert {r["topic"] for r in results} == {"physics", "pure-math"} and (run_dir / "results.csv").exists()
    assert (run_dir / "config.json").exists() and (run_dir / "physics" / "prompt.md").exists()
    log_text = (fake_env / "logs" / "run_t1.log").read_text(encoding="utf-8")
    assert "- physics (Physics)" in log_text and "final answer:" in log_text  # full prompt + answer logged


def test_split_vs_merged_batching_and_overrides(fake_env: Path) -> None:
    """Same 2 cells: no merge -> 2 agents, merged interval -> 1 agent; per-run overrides reach the run."""
    split = _run(fake_env, "split", make_config("Physics", intervals=("day", "week"), merge=[]))
    merged = _run(fake_env, "merged", make_config("Physics", intervals=("day", "week"), merge=["interval"],
                                                  overrides={"items_per_cell": 3}))
    assert len(read_json(split / "status.json")["agents"]) == 2
    [agent] = read_json(merged / "status.json")["agents"].values()
    assert agent["cells"] == 2 and agent["label"] == "Physics · Papers · Viral news · Rigorous"
    assert "up to 3 items" in next(merged.glob("*/prompt.md")).read_text(encoding="utf-8")


def test_cli_without_config_marks_run_failed(fake_env: Path) -> None:
    """No saved workspace -> exit code 1 and a failed status the dashboard can show."""
    assert main(["run", "--run-id", "t2"]) == 1
    status = read_json(fake_env / "runs" / "t2" / "status.json")
    assert status["state"] == "failed" and "config" in status["error"]
