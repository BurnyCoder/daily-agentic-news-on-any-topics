"""Command-line entry point: `agentic-news run [--run-id ID] [--selection PATH]`.

Local: parses arguments (https://docs.python.org/3/library/argparse.html), loads settings, sets up the run
log, runs the pipeline, and records a failed status if anything outside the agents breaks.
Global context: the Streamlit dashboard starts `python -m agentic_news.cli run --run-id <id>` in the
background; the same command works from a terminal or Windows Task Scheduler for daily runs.
"""

import argparse  # CLI parsing
import logging  # top-level progress/errors
import sys  # exit code
from pathlib import Path  # --selection path

from agentic_news.logging_setup import setup_logging  # run log + terminal
from agentic_news.pipeline import run_pipeline  # the wrapper with all phases
from agentic_news.settings import load_settings  # .env configuration
from agentic_news.store import new_run_id, now, read_json, write_json  # run id + failed status

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Run the requested command; return the process exit code."""
    parser = argparse.ArgumentParser(prog="agentic-news", description="Launch one Codex agent per selected topic.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run all selected topic agents and save results under runs/<run_id>/")
    run.add_argument("--run-id", help="folder name under runs/ (default: current timestamp)")
    run.add_argument("--selection", type=Path, help="selection JSON (default: the dashboard's saved selection)")
    args = parser.parse_args(argv)
    settings = load_settings()
    run_id = args.run_id or new_run_id()
    log_path = setup_logging(settings.logs_dir, run_id)
    log.info("run %s starting; log file %s; settings %s", run_id, log_path, settings)
    try:
        run_dir = run_pipeline(run_id, settings, args.selection)
    except Exception as exc:  # recorded so the dashboard shows why the run died
        log.exception("run %s failed", run_id)
        status_path = settings.runs_dir / run_id / "status.json"
        status = read_json(status_path, default={"run_id": run_id, "agents": {}})
        write_json(status_path, {**status, "state": "failed", "error": repr(exc), "ended": now()})
        return 1
    log.info("results: %s", run_dir / "results.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
