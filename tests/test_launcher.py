"""Tests for launcher.py — background runs exactly as the dashboard starts and stops them.

Global context: launch_run spawns a real `python -m agentic_news.cli run` process (driving fake codex agents);
the dashboard only ever sees the files it writes, which is what these tests poll.
"""

import time  # polling deadline
from pathlib import Path  # temporary folders

import psutil  # verify killed processes

from agentic_news.launcher import is_active, launch_run, stop_run  # functions under test
from agentic_news.settings import load_settings  # picks up fake_env overrides
from agentic_news.store import load_results, read_json  # what the dashboard reads
from conftest import make_config  # small configs


def _wait(predicate, seconds: float = 60) -> None:
    """Poll until predicate() is true or fail after `seconds`."""
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.2)


def test_background_run_finishes_with_results(fake_env: Path) -> None:
    """Launch -> status goes active -> done; results are readable; the run is no longer active."""
    settings = load_settings()
    run_id = launch_run(make_config("Physics", "LLMs"), settings)
    status_path = settings.runs_dir / run_id / "status.json"
    assert read_json(status_path)["state"] in ("starting", "running")  # written immediately for the UI
    _wait(lambda: (read_json(status_path) or {}).get("state") == "done")
    assert not is_active(read_json(status_path))
    assert {r["topic"] for r in load_results(settings.runs_dir / run_id)} == {"physics", "llms"}


def test_stop_kills_a_running_run(fake_env: Path) -> None:
    """Stopping a run with a hanging agent kills the run process tree and marks it stopped."""
    settings = load_settings()
    run_id = launch_run(make_config("MODE=hang"), settings)
    run_dir = settings.runs_dir / run_id
    _wait(lambda: (run_dir / "mode-hang" / "child_pid.txt").exists())  # agent and its child are running
    assert is_active(read_json(run_dir / "status.json"))
    stop_run(run_dir)
    status = read_json(run_dir / "status.json")
    child = int((run_dir / "mode-hang" / "child_pid.txt").read_text(encoding="utf-8"))
    time.sleep(0.5)  # let the OS reap processes
    assert status["state"] == "stopped" and not is_active(status)
    assert not psutil.pid_exists(child) or psutil.Process(child).status() == psutil.STATUS_ZOMBIE
