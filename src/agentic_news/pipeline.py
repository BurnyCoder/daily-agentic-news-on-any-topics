"""Pipeline wrapper: one "Get News" run, expressed as clearly named phases.

Local: run_pipeline = load_selection -> build_jobs -> prepare_agent_dirs -> run_agents -> collect_results
-> save_results. Each phase is a small function here or an imported one from its own module.
Global context: cli.py calls run_pipeline (headless, scheduler, or launched in the background by the
Streamlit dashboard); everything a run produces lives under runs/<run_id>/.
"""

import logging  # phase-level progress in the run log
from datetime import date  # "today" anchors every interval
from pathlib import Path  # run folders

from agentic_news.catalog import Job, build_jobs  # rows -> one job per topic
from agentic_news.codex_runner import AgentResult, AgentSpec, run_agents  # agent processes
from agentic_news.prompts import build_prompt  # per-topic instructions
from agentic_news.schema import build_output_schema  # per-topic --output-schema
from agentic_news.settings import Settings  # configuration
from agentic_news.store import StatusBoard, read_json, save_results, write_json  # files

log = logging.getLogger(__name__)


def load_selection(run_dir: Path, settings: Settings, selection_path: Path | None = None) -> list[dict]:
    """Rows from --selection, else this run's snapshot (dashboard launch), else the saved dashboard selection."""
    for path in (selection_path, run_dir / "selection.json", settings.data_dir / "selection.json"):
        if path is not None and (rows := read_json(path)) is not None:
            log.info("selection loaded from %s", path)
            return rows
    raise FileNotFoundError("no topic selection found: save one in the dashboard or pass --selection PATH")


def prepare_agent_dirs(jobs: list[Job], run_dir: Path, run_id: str, today: date, settings: Settings) -> list[AgentSpec]:
    """Create runs/<run_id>/<slug>/ with schema.json + prompt.md for each job."""
    specs = []
    for job in jobs:
        agent_dir = (run_dir / job.slug).resolve()  # absolute: codex gets --cd and file paths
        agent_dir.mkdir(parents=True, exist_ok=True)
        write_json(agent_dir / "schema.json", build_output_schema(job))
        prompt = build_prompt(job, today, settings.items_per_cell, settings.max_items_per_agent)
        (agent_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        specs.append(AgentSpec(job=job, agent_dir=agent_dir, prompt=prompt, run_id=run_id, today=today))
    return specs


def collect_results(results: list[AgentResult]) -> list[dict]:
    """Flatten every agent's rows into one table."""
    return [row for result in results for row in result.items]


def run_pipeline(run_id: str, settings: Settings, selection_path: Path | None = None,
                 today: date | None = None) -> Path:
    """Execute one full run and return its folder."""
    today = today or date.today()
    run_dir = settings.runs_dir / run_id
    rows = load_selection(run_dir, settings, selection_path)
    write_json(run_dir / "selection.json", rows)  # snapshot: what exactly this run searched for
    jobs = build_jobs(rows)
    log.info("run %s: %d topic agent(s), %d cells, model %s", run_id, len(jobs), sum(j.cells for j in jobs),
             settings.codex_model)
    board = StatusBoard(run_dir / "status.json", run_id, jobs)
    specs = prepare_agent_dirs(jobs, run_dir, run_id, today, settings)
    results = run_agents(specs, settings, board)
    rows_out = collect_results(results)
    save_results(run_dir, rows_out)
    board.finish("done" if not results or any(r.state == "done" for r in results) else "failed")
    log.info("run %s finished: %d items; %s", run_id, len(rows_out),
             ", ".join(f"{r.job.slug}={r.state}({len(r.items)})" for r in results) or "no agents")
    return run_dir
