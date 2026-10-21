"""Launcher: start, inspect and stop a run as a background `agentic-news run` process.

Local: `launch_run` snapshots the selection into runs/<run_id>/selection.json and starts
`python -m agentic_news.cli run --run-id <id>` with CREATE_NEW_PROCESS_GROUP on Windows, so Ctrl+C in the
Streamlit terminal does not kill it while its output still streams into that terminal
(https://docs.python.org/3/library/subprocess.html#subprocess.CREATE_NEW_PROCESS_GROUP).
Global context: the Streamlit dashboard calls these; the run itself is driven by cli -> pipeline, and the
dashboard only reads the files the run writes (status.json, results).
"""

import os  # platform check for process-group flags
import subprocess  # background CLI process
import sys  # same interpreter/venv as the dashboard
from pathlib import Path  # run folders

import psutil  # pid liveness check (os.kill(pid, 0) would terminate the process on Windows)

from agentic_news.codex_runner import kill_tree  # reuse the process-tree kill used for timeouts
from agentic_news.settings import PROJECT_ROOT, Settings  # paths
from agentic_news.store import new_run_id, now, read_json, write_json  # run files

_GROUP = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}


def launch_run(rows: list[dict], settings: Settings) -> str:
    """Write the selection snapshot, start the CLI in the background, return the new run id."""
    run_id = new_run_id()
    run_dir = settings.runs_dir / run_id
    write_json(run_dir / "selection.json", rows)  # the CLI reads this snapshot first
    proc = subprocess.Popen([sys.executable, "-m", "agentic_news.cli", "run", "--run-id", run_id],
                            cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL, **_GROUP)
    write_json(run_dir / "status.json", {"run_id": run_id, "state": "starting", "pid": proc.pid,
                                         "started": now(), "ended": None, "agents": {}})  # replaced by the run
    return run_id


def is_active(status: dict | None) -> bool:
    """True while the run's process is alive and the run has not finished."""
    if not status or status.get("state") not in ("starting", "running"):
        return False
    pid = status.get("pid")
    return bool(pid) and psutil.pid_exists(pid)


def stop_run(run_dir: Path) -> None:
    """Kill the run process with all its Codex agents and mark the run stopped."""
    status = read_json(run_dir / "status.json", default={}) or {}
    if status.get("pid"):
        kill_tree(status["pid"])
    write_json(run_dir / "status.json", {**status, "state": "stopped", "ended": now()})
