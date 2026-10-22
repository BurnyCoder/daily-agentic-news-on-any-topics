"""Codex runner: launch one unsandboxed `codex exec` process per batch of cells, stream its events, collect its answer.

Local: `build_command` assembles the CLI flags (https://learn.chatgpt.com/docs/non-interactive-mode,
`codex exec --help`); `run_agent` starts the process with the prompt on stdin, streams stdout JSONL line by
line into the log, raw event file and StatusBoard, enforces a timeout by killing the whole process tree
(psutil, https://psutil.io/recipes/#controlling-processes), and validates the final answer with retries.
`run_agents` runs agents in a thread pool: each worker just blocks on its own subprocess
(https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor).
Global context: called by pipeline.run_pipeline; results feed the dashboard's table.
"""

import json  # decode JSONL event lines
import logging  # full prompts/events/answers go to the run log + terminal
import subprocess  # Popen for the codex processes
import threading  # stderr pump + timeout timer
from concurrent.futures import ThreadPoolExecutor  # bounded parallelism
from dataclasses import dataclass, field  # spec/result records
from datetime import date  # "today" for parsing
from pathlib import Path  # agent folders

import psutil  # cross-platform process-tree kill

from agentic_news.catalog import Dimension, Job  # the batch of cells and the dimensions describing them
from agentic_news.events import describe_event, is_fatal_error, search_urls  # log, retry policy, searched URLs
from agentic_news.schema import parse_final  # validation of the final JSON
from agentic_news.settings import Settings  # flags, limits
from agentic_news.store import StatusBoard, now, write_json  # live status + per-agent items file

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentSpec:
    """Everything one agent needs: job, dimensions, its folder (with schema.json), the full prompt, run metadata."""

    job: Job
    dims: list[Dimension]
    agent_dir: Path
    prompt: str
    run_id: str
    today: date


@dataclass
class AgentResult:
    """Outcome of one agent after all attempts."""

    job: Job
    state: str  # done | failed | timeout
    items: list[dict] = field(default_factory=list)
    coverage_notes: str = ""
    error: str = ""
    attempts: int = 0
    dropped: int = 0  # items the agent filed in cells it was not asked for


def build_command(settings: Settings, agent_dir: Path) -> list[str]:
    """argv for one agent; prompt is read from stdin (`-`), answer lands in agent_dir/final.json."""
    cmd = [*settings.codex_cmd, "exec", "--json", "--color", "never", "--model", settings.codex_model,
           "-c", f'model_reasoning_effort="{settings.codex_reasoning_effort}"',
           "-c", f'model_reasoning_summary="{settings.codex_reasoning_summary}"',
           "-c", f'web_search="{settings.codex_web_search}"',  # exec has no --search flag; config key instead
           "-c", "project_doc_max_bytes=0",  # don't feed this repo's AGENTS.md to the news agents
           "--dangerously-bypass-approvals-and-sandbox",  # user's choice: no sandbox, no approvals
           "--ephemeral", "--skip-git-repo-check"]  # no session files; agent folders aren't repos
    if settings.codex_ignore_user_config:
        cmd.append("--ignore-user-config")  # don't load ~/.codex/config.toml (e.g. personal MCP servers)
    for feature in settings.codex_disable_features:
        cmd += ["--disable", feature]
    return cmd + ["--cd", str(agent_dir), "--output-schema", str(agent_dir / "schema.json"),
                  "--output-last-message", str(agent_dir / "final.json"), "-"]


def kill_tree(pid: int) -> None:
    """Kill a process and all its descendants (codex spawns shells; killing only codex.exe would orphan them)."""
    try:
        parent = psutil.Process(pid)
        procs = parent.children(recursive=True) + [parent]
    except psutil.NoSuchProcess:
        return
    for proc in procs:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(procs, timeout=5)


def _pump_stderr(stream, tag: str, tail: list[str]) -> None:
    """Log every stderr line in real time and keep the last few for error messages."""
    for line in stream:
        log.info("%s [stderr] %s", tag, line.rstrip())
        tail[:] = (tail + [line.strip()])[-5:]


def _run_once(spec: AgentSpec, settings: Settings, board: StatusBoard, attempt: int) -> AgentResult:
    """One attempt: run codex to completion (or timeout) and parse its final answer."""
    slug, tag = spec.job.slug, f"[{spec.job.slug}#{attempt}]"
    final_path = spec.agent_dir / "final.json"
    # In --json mode -o is written only when the turn completes (codex-rs/exec/src/event_processor_with_jsonl_output.rs
    # in openai/codex rust-v0.163.0), so never reuse a previous attempt's file.
    final_path.unlink(missing_ok=True)
    cmd = build_command(settings, spec.agent_dir)
    last_message, seen_urls, stderr_tail = "", set(), []
    timed_out = threading.Event()
    # Open the raw event file first, so a bad path fails before any process exists.
    with open(spec.agent_dir / f"events_attempt{attempt}.jsonl", "w", encoding="utf-8") as raw:
        log.info("%s launching: %s", tag, subprocess.list2cmdline(cmd))
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)  # line-buffered text
        timer = threading.Timer(settings.agent_timeout_minutes * 60, lambda: (timed_out.set(), kill_tree(proc.pid)))
        timer.daemon = True  # never keeps the interpreter alive
        pump = threading.Thread(target=_pump_stderr, args=(proc.stderr, tag, stderr_tail), daemon=True)
        try:
            board.update(slug, state="running", attempt=attempt, started=now(), pid=proc.pid)
            timer.start()
            pump.start()  # start reading stderr before writing stdin so neither pipe can fill up and block
            try:
                # bytes: text-mode stdin would turn "\n" into os.linesep ("\r\n" on Windows), per the subprocess docs
                proc.stdin.buffer.write(spec.prompt.encode("utf-8"))
                proc.stdin.close()
            except OSError as exc:  # codex exited early (e.g. bad flag) — its stderr explains why
                log.warning("%s could not send prompt: %s", tag, exc)
            for line in proc.stdout:  # yields each JSONL line as soon as codex flushes it
                raw.write(line)
                raw.flush()
                last_message = _handle_line(line, slug, tag, board, seen_urls) or last_message
            proc.wait()
        finally:  # on any error above, never leave an unsandboxed agent running
            timer.cancel()
            if proc.poll() is None:
                kill_tree(proc.pid)
    pump.join(timeout=5)
    if timed_out.is_set():
        return AgentResult(spec.job, "timeout", error=f"killed after {settings.agent_timeout_minutes} min",
                           attempts=attempt)
    answer = final_path.read_text(encoding="utf-8") if final_path.exists() else last_message
    log.info("%s exit code %s, final answer:\n%s", tag, proc.returncode, answer)
    try:
        rows, notes, dropped = parse_final(answer, spec.job, spec.dims, spec.run_id, spec.today, seen_urls)
    except ValueError as exc:
        reason = board.data["agents"][slug]["error"] or " | ".join(stderr_tail) or str(exc)
        return AgentResult(spec.job, "failed", error=f"exit {proc.returncode}: {reason}", attempts=attempt)
    if dropped:
        log.warning("%s dropped %d item(s) filed in cells outside this batch", tag, dropped)
    return AgentResult(spec.job, "done", items=rows, coverage_notes=notes, attempts=attempt, dropped=dropped)


def _handle_line(line: str, slug: str, tag: str, board: StatusBoard, seen_urls: set[str]) -> str | None:
    """Log + count one stdout line, collect searched URLs; return the agent message text if the line has one."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        log.info("%s %s", tag, line.rstrip())  # non-JSON output is still logged verbatim
        return None
    text = describe_event(event)
    if text:
        log.info("%s %s", tag, text)
    board.apply(slug, event, text)
    seen_urls.update(search_urls(event))  # later marks which answer links really came from search
    item = event.get("item") or {}
    return item.get("text") if event.get("type") == "item.completed" and item.get("type") == "agent_message" else None


def run_agent(spec: AgentSpec, settings: Settings, board: StatusBoard) -> AgentResult:
    """Run one agent with retries (none after timeouts or usage-limit/auth errors)."""
    log.info("[%s] %s — prompt (%d cells):\n%s", spec.job.slug, spec.job.label, len(spec.job.cells), spec.prompt)
    result = AgentResult(spec.job, "failed", error="not started")
    try:
        for attempt in range(1, settings.agent_max_retries + 2):
            result = _run_once(spec, settings, board, attempt)
            if result.state != "failed" or is_fatal_error(result.error):
                break  # done, timed out, or retrying cannot help
            log.warning("[%s] attempt %d failed: %s", spec.job.slug, attempt, result.error)
    except Exception as exc:  # never let one agent crash the whole run
        log.exception("[%s] runner error", spec.job.slug)
        result = AgentResult(spec.job, "failed", error=repr(exc), attempts=result.attempts)
    write_json(spec.agent_dir / "items.json", result.items)  # partial results for the dashboard mid-run
    board.update(spec.job.slug, state=result.state, ended=now(), items=len(result.items), error=result.error,
                 coverage_notes=result.coverage_notes, dropped=result.dropped)
    log.info("[%s] %s with %d items after %d attempt(s)", spec.job.slug, result.state, len(result.items),
             result.attempts)
    return result


def run_agents(specs: list[AgentSpec], settings: Settings, board: StatusBoard) -> list[AgentResult]:
    """Run all agents, at most `max_parallel_agents` at a time; results keep the input order."""
    workers = max(1, min(settings.max_parallel_agents, len(specs)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="agent") as pool:
        return list(pool.map(lambda spec: run_agent(spec, settings, board), specs))
