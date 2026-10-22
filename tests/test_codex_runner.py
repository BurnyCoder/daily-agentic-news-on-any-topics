"""Tests for codex_runner.py — command construction and running agents against fixtures/fake_codex.py.

Global context: these cover the process plumbing of real runs (stdin prompt, live JSONL streaming, status
updates, retries, timeouts with process-tree kill) without spending tokens.
"""

import json  # read event files
import sys  # current interpreter runs the fake codex script
import time  # give the OS a moment after killing processes
from datetime import date  # fixed "today"
from pathlib import Path  # temporary agent folders

import psutil  # check that killed processes are gone

from agentic_news.catalog import Job, default_dimensions  # one-cell job + the dimensions describing it
from agentic_news.codex_runner import AgentSpec, build_command, run_agent, run_agents  # under test
from agentic_news.schema import build_output_schema  # schema file the fake reads
from agentic_news.settings import Settings  # runner configuration
from agentic_news.store import StatusBoard, read_json  # status board the runner updates

FAKE = Path(__file__).parent / "fixtures" / "fake_codex.py"
FAST = Settings(codex_cmd=(sys.executable, str(FAKE)), agent_timeout_minutes=0.05, agent_max_retries=1)
DIMS = default_dimensions()


def _job(slug: str = "physics") -> Job:
    return Job(slug=slug, label=slug.title(), cells=(("physics", "day", "paper", "viral_news", "rigorous"),))


def _spec(tmp_path: Path, mode: str, slug: str = "physics") -> AgentSpec:
    """Agent folder with schema.json and a prompt that selects the fake's behaviour."""
    job = _job(slug)
    agent_dir = tmp_path / slug
    agent_dir.mkdir()
    (agent_dir / "schema.json").write_text(json.dumps(build_output_schema(job, DIMS)), encoding="utf-8")
    prompt = f"MODE={mode}\nUnicode check: é ∑ 漢字\nline two\n"
    return AgentSpec(job=job, dims=DIMS, agent_dir=agent_dir, prompt=prompt, run_id="r1", today=date(2026, 10, 22))


def test_build_command_has_the_planned_flags(tmp_path: Path) -> None:
    """Default settings produce the unsandboxed gpt-6-luna web-search command with stdin prompt."""
    cmd = build_command(Settings(), tmp_path)
    assert cmd[:2] == ["codex", "exec"] and cmd[-1] == "-"  # prompt comes from stdin
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd and "--json" in cmd
    assert cmd[cmd.index("--model") + 1] == "gpt-6-luna"
    assert 'web_search="live"' in cmd and "project_doc_max_bytes=0" in cmd
    assert cmd[cmd.index("--cd") + 1] == str(tmp_path)
    assert cmd[cmd.index("--output-last-message") + 1] == str(tmp_path / "final.json")
    assert cmd.count("--disable") == 6 and "--ignore-user-config" in cmd


def test_successful_agent(tmp_path: Path) -> None:
    """Prompt arrives byte-identical, raw events are saved, rows are parsed, status shows done."""
    spec = _spec(tmp_path, "ok")
    board = StatusBoard(tmp_path / "status.json", "r1", [spec.job])
    result = run_agent(spec, FAST, board)
    assert result.state == "done" and result.items[0]["topic"] == "physics" and result.coverage_notes == "fake notes"
    assert result.items[0]["url_seen"] is True  # the fake's search results contained the answer's link
    assert (spec.agent_dir / "received_prompt.txt").read_bytes() == spec.prompt.encode("utf-8")
    raw = (spec.agent_dir / "events_attempt1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(raw) == 5 and json.loads(raw[0])["type"] == "thread.started"  # every line kept raw
    agent = read_json(tmp_path / "status.json")["agents"]["physics"]
    assert agent["state"] == "done" and agent["searches"] == 1 and agent["items"] == 1 and agent["attempt"] == 1


def test_retry_rules(tmp_path: Path) -> None:
    """Invalid answers are retried; transient failures use all attempts; usage limits stop immediately."""
    specs = {m: _spec(tmp_path, m, slug=m.replace("_", "-")) for m in ("flaky", "fail", "usage")}
    board = StatusBoard(tmp_path / "status.json", "r1", [s.job for s in specs.values()])
    flaky, fail, usage = (run_agent(specs[m], FAST, board) for m in ("flaky", "fail", "usage"))
    assert flaky.state == "done" and flaky.attempts == 2  # bad JSON first, valid second
    assert fail.state == "failed" and fail.attempts == 2 and "stream disconnected" in fail.error
    assert usage.state == "failed" and usage.attempts == 1  # no retry on usage limits


def test_timeout_kills_the_whole_process_tree(tmp_path: Path) -> None:
    """A hanging agent is killed with its child process after the timeout and is not retried."""
    spec = _spec(tmp_path, "hang")
    result = run_agent(spec, FAST, StatusBoard(tmp_path / "status.json", "r1", [spec.job]))
    assert result.state == "timeout" and result.attempts == 1
    time.sleep(0.5)  # let Windows reap the processes
    child = int((spec.agent_dir / "child_pid.txt").read_text(encoding="utf-8"))
    assert not psutil.pid_exists(child) or psutil.Process(child).status() == psutil.STATUS_ZOMBIE


def test_run_agents_in_parallel(tmp_path: Path) -> None:
    """Three agents with a pool of two all finish and keep input order."""
    specs = [_spec(tmp_path, "ok", slug=s) for s in ("a", "b", "c")]
    board = StatusBoard(tmp_path / "status.json", "r1", [s.job for s in specs])
    results = run_agents(specs, Settings(codex_cmd=FAST.codex_cmd, max_parallel_agents=2), board)
    assert [r.job.slug for r in results] == ["a", "b", "c"] and all(r.state == "done" for r in results)
