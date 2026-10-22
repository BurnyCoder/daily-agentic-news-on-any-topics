"""Pipeline wrapper: one "Get News" run, expressed as clearly named phases.

Local: run_pipeline = load_config -> expand_rules (granular cells) -> build_jobs (batch cells into agents by the
user's merge choice) -> prepare_agent_dirs -> run_agents -> collect_results -> save_results. Each phase is a small
function here or an imported one from its own module.
Global context: cli.py calls run_pipeline (headless, scheduler, or launched in the background by the
Streamlit dashboard); everything a run produces lives under runs/<run_id>/.
"""

import logging  # phase-level progress in the run log
from datetime import date  # "today" anchors every interval
from pathlib import Path  # run folders

from agentic_news.catalog import Job, build_jobs, expand_rules, validate_dimensions  # cells and batches
from agentic_news.codex_runner import AgentResult, AgentSpec, run_agents  # agent processes
from agentic_news.config import RunConfig, config_from_dict, config_to_dict  # what to run and how
from agentic_news.prompts import build_prompt  # per-batch instructions
from agentic_news.schema import build_output_schema, result_columns  # per-batch --output-schema, columns
from agentic_news.settings import Settings, apply_overrides  # configuration
from agentic_news.store import StatusBoard, read_json, save_results, write_json  # files

log = logging.getLogger(__name__)


def load_config(run_dir: Path, settings: Settings, config_path: Path | None = None) -> RunConfig:
    """Config from --config, else this run's snapshot (dashboard launch), else the saved dashboard workspace."""
    for path in (config_path, run_dir / "config.json", settings.data_dir / "workspace.json"):
        if path is not None and (data := read_json(path)) is not None:
            log.info("config loaded from %s", path)
            return config_from_dict(data)
    raise FileNotFoundError("no config found: save a workspace in the dashboard or pass --config PATH")


def prepare_agent_dirs(jobs: list[Job], cfg: RunConfig, run_dir: Path, run_id: str, today: date,
                       settings: Settings) -> list[AgentSpec]:
    """Create runs/<run_id>/<slug>/ with schema.json + prompt.md for each batch."""
    specs = []
    for job in jobs:
        agent_dir = (run_dir / job.slug).resolve()  # absolute: codex gets --cd and file paths
        agent_dir.mkdir(parents=True, exist_ok=True)
        write_json(agent_dir / "schema.json", build_output_schema(job, cfg.dimensions))
        prompt = build_prompt(job, cfg.dimensions, today, settings.items_per_cell, settings.max_items_per_agent,
                              cfg.prompt_rules)
        (agent_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        specs.append(AgentSpec(job=job, dims=cfg.dimensions, agent_dir=agent_dir, prompt=prompt, run_id=run_id,
                               today=today))
    return specs


def collect_results(results: list[AgentResult]) -> list[dict]:
    """Flatten every agent's rows into one table."""
    return [row for result in results for row in result.items]


def run_pipeline(run_id: str, settings: Settings, config_path: Path | None = None,
                 today: date | None = None) -> Path:
    """Execute one full run and return its folder."""
    today = today or date.today()
    run_dir = settings.runs_dir / run_id
    cfg = load_config(run_dir, settings, config_path)
    write_json(run_dir / "config.json", config_to_dict(cfg))  # snapshot: exactly what this run searched for
    if errors := validate_dimensions(cfg.dimensions):
        raise ValueError("invalid dimensions: " + "; ".join(errors))
    settings = apply_overrides(settings, cfg.overrides)  # dashboard's per-run choices win over .env
    cells = expand_rules(cfg.rules, cfg.dimensions)
    jobs = build_jobs(cells, cfg.dimensions, cfg.merge, cfg.max_cells_per_agent)
    log.info("run %s: %d cell(s) in %d agent(s) (merged: %s, max cells/agent: %s), %d in parallel, model %s; "
             "effective settings %s", run_id, len(cells), len(jobs), cfg.merge or "none",
             cfg.max_cells_per_agent or "no limit", settings.max_parallel_agents, settings.codex_model, settings)
    board = StatusBoard(run_dir / "status.json", run_id, jobs)
    specs = prepare_agent_dirs(jobs, cfg, run_dir, run_id, today, settings)
    results = run_agents(specs, settings, board)
    rows_out = collect_results(results)
    save_results(run_dir, rows_out, result_columns(cfg.dimensions))
    board.finish("done" if not results or any(r.state == "done" for r in results) else "failed")
    log.info("run %s finished: %d items; %s", run_id, len(rows_out),
             ", ".join(f"{r.job.slug}={r.state}({len(r.items)})" for r in results) or "no agents")
    return run_dir
