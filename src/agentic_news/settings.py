"""Configuration: read `.env` (plus process environment overrides) into one frozen Settings object.

Local: each Settings field maps to an UPPER_CASE key in `.env`; the field's default value decides how the
string is converted (bool, int, float, comma tuple, path).
Global context: every phase (pipeline, runner, dashboard) receives the same Settings instance. Values are read
with `dotenv_values`, which returns a dict and does NOT write into `os.environ`
(https://saurabh-kumar.com/python-dotenv/#other-use-cases), so nothing from `.env` leaks into the environment
inherited by the unsandboxed Codex agents.
"""

import os  # os.environ supplies per-run overrides, e.g. `MAX_PARALLEL_AGENTS=2 uv run agentic-news run`
from collections.abc import Mapping  # type of the environment mapping (injectable for tests)
from dataclasses import dataclass, fields, replace  # frozen config record, field iteration, modified copies
from pathlib import Path  # filesystem paths for runs/logs/data

from dotenv import dotenv_values  # parses .env into a dict without touching os.environ

# Project root = two levels above src/agentic_news/settings.py; relative paths in .env resolve against it.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TRUE = {"1", "true", "yes", "on"}  # accepted spellings of a true boolean


@dataclass(frozen=True)
class Settings:
    """All tunables; defaults mirror `.env.example`."""

    codex_cmd: tuple[str, ...] = ("codex",)  # argv prefix that launches Codex (a fake script in tests)
    codex_model: str = "gpt-6-luna"  # slug from `codex debug models`
    codex_reasoning_effort: str = "medium"  # gpt-6-luna supports low|medium|high|xhigh|max
    codex_reasoning_summary: str = "auto"  # makes reasoning summaries appear in the JSONL stream/logs
    codex_web_search: str = "live"  # https://learn.chatgpt.com/docs/config-file/config-basic.md
    codex_ignore_user_config: bool = True  # skip ~/.codex/config.toml (e.g. MCP servers) for news agents
    codex_disable_features: tuple[str, ...] = (  # names from `codex features list`
        "plugins", "remote_plugin", "apps", "plugin_sharing", "tool_suggest", "multi_agent")
    max_parallel_agents: int = 6  # thread-pool size = concurrent Codex processes
    agent_timeout_minutes: float = 30.0  # per-attempt wall clock before the process tree is killed
    agent_max_retries: int = 1  # extra attempts after a failure/invalid answer
    items_per_cell: int = 2  # items requested per interval x type x source x variant
    max_items_per_agent: int = 60  # cap on one agent's answer size
    confirm_above_agents: int = 30  # dashboard asks for explicit confirmation above this many agents
    runs_dir: Path = Path("runs")  # per-run folders (status, results, per-agent artifacts)
    logs_dir: Path = Path("logs")  # timestamped run logs
    data_dir: Path = Path("data")  # dashboard's saved topic selection


def _convert(raw: str, default: object, root: Path) -> object:
    """Convert one .env string to the type of the field's default value."""
    raw = raw.strip()  # tolerate stray spaces around values
    if isinstance(default, bool):  # check bool before int: bool is a subclass of int
        return raw.lower() in _TRUE
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, tuple):  # comma-separated list; commas are safer than spaces in Windows paths
        return tuple(part.strip() for part in raw.split(",") if part.strip())
    if isinstance(default, Path):
        return root / raw  # relative paths are anchored at the project root
    return raw  # plain string


def load_settings(env_file: Path | None = None, root: Path = PROJECT_ROOT,
                  environ: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from `.env` then environment overrides; unknown keys are ignored."""
    env = os.environ if environ is None else environ  # tests inject an empty mapping
    file_values = dotenv_values(env_file or root / ".env")  # missing file -> empty dict
    values: dict[str, object] = {}
    for f in fields(Settings):  # walk declared fields so only known keys are read
        key = f.name.upper()  # field codex_model <-> key CODEX_MODEL
        raw = env.get(key, file_values.get(key))  # environment wins over .env
        if raw is not None:
            values[f.name] = _convert(raw, f.default, root)
    paths = {name: root / getattr(Settings, name) for name in ("runs_dir", "logs_dir", "data_dir")
             if name not in values}  # anchor default relative paths at the root too
    return Settings(**{**paths, **values})


def apply_overrides(settings: Settings, overrides: Mapping[str, object]) -> Settings:
    """Copy of settings with per-run values from the dashboard (any JSON type); paths can't be overridden."""
    allowed = {f.name: f.default for f in fields(Settings) if not isinstance(f.default, Path)}
    if unknown := set(overrides) - set(allowed):
        raise ValueError(f"unknown or non-overridable settings: {sorted(unknown)}")
    as_text = {k: ",".join(v) if isinstance(v, (list, tuple)) else str(v) for k, v in overrides.items()}
    return replace(settings, **{k: _convert(raw, allowed[k], PROJECT_ROOT) for k, raw in as_text.items()})
