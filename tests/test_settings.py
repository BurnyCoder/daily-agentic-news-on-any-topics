"""Tests for settings.py — .env parsing into a frozen Settings object.

Global context: every other module receives a Settings instance, so wrong parsing here silently changes
how agents are launched (model, parallelism, timeouts).
"""

import os  # used to assert that loading .env does not leak values into the process environment
from pathlib import Path  # paths for temporary .env files and expected directories

from agentic_news.settings import Settings, load_settings  # module under test


def test_defaults_without_env_file(tmp_path: Path) -> None:
    """A missing .env yields the documented defaults with paths resolved under the given root."""
    s = load_settings(env_file=tmp_path / "missing.env", root=tmp_path, environ={})  # no .env, no env vars
    assert s.codex_cmd == ("codex",)  # default launcher is the codex executable on PATH
    assert s.codex_model == "gpt-6-luna"  # model requested by the user
    assert s.codex_web_search == "live"  # live web search is on by default
    assert s.codex_ignore_user_config is True  # agents skip ~/.codex/config.toml by default
    assert "plugins" in s.codex_disable_features  # plugin download is disabled for faster startup
    assert s.max_parallel_agents == 6 and s.agent_max_retries == 1  # documented run limits
    assert s.runs_dir == tmp_path / "runs"  # relative paths resolve against the project root


def test_env_file_values_are_parsed_by_type(tmp_path: Path) -> None:
    """Ints, floats, bools, comma tuples and paths are converted from their .env strings."""
    env = tmp_path / ".env"  # temporary .env file
    env.write_text(
        "CODEX_CMD=python, fake.py\nMAX_PARALLEL_AGENTS=2\nAGENT_TIMEOUT_MINUTES=0.5\n"
        "CODEX_IGNORE_USER_CONFIG=no\nCODEX_DISABLE_FEATURES=\nRUNS_DIR=out/runs\n",
        encoding="utf-8",
    )
    s = load_settings(env_file=env, root=tmp_path, environ={})  # parse the file only
    assert s.codex_cmd == ("python", "fake.py")  # comma-separated parts, whitespace stripped
    assert s.max_parallel_agents == 2  # int conversion
    assert s.agent_timeout_minutes == 0.5  # float conversion
    assert s.codex_ignore_user_config is False  # "no" parses as False
    assert s.codex_disable_features == ()  # empty value means no disabled features
    assert s.runs_dir == tmp_path / "out" / "runs"  # relative path under root


def test_environment_overrides_env_file_and_is_not_modified(tmp_path: Path) -> None:
    """Process environment wins over .env, and loading never writes into os.environ."""
    env = tmp_path / ".env"  # .env sets one value
    env.write_text("ITEMS_PER_CELL=5\n", encoding="utf-8")
    before = dict(os.environ)  # snapshot of the real environment
    s = load_settings(env_file=env, root=tmp_path, environ={"ITEMS_PER_CELL": "1"})  # override via env
    assert s.items_per_cell == 1  # environment value takes precedence
    assert dict(os.environ) == before  # nothing leaked into the environment the agents inherit
    assert isinstance(s, Settings)  # frozen dataclass instance
