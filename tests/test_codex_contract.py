"""Contract tests against the installed Codex CLI (marker `cli`, no tokens): run with `uv run pytest -m cli`.

Global context: the runner depends on exact flag, feature and model names of codex-cli; these tests fail fast
after a Codex update renames something, instead of every agent failing at run time.
"""

import json  # parse `codex debug models`
import subprocess  # call the real codex binary
from pathlib import Path  # dummy agent folder for build_command

import pytest  # markers

from agentic_news.codex_runner import build_command  # flags under test
from agentic_news.settings import load_settings  # the user's real configuration

pytestmark = pytest.mark.cli
SETTINGS = load_settings()


def _codex(*args: str) -> str:
    """stdout of `codex <args>`."""
    return subprocess.run([*SETTINGS.codex_cmd, *args], capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


def test_exec_flags_exist() -> None:
    """Every --flag the runner passes is documented by `codex exec --help`."""
    help_text = _codex("exec", "--help")
    flags = {a for a in build_command(SETTINGS, Path("agent"))[len(SETTINGS.codex_cmd):] if a.startswith("--")}
    assert flags and all(flag in help_text for flag in flags), flags - {f for f in flags if f in help_text}


def test_disabled_features_exist() -> None:
    """Every feature in CODEX_DISABLE_FEATURES is listed by `codex features list`."""
    names = {line.split()[0] for line in _codex("features", "list").splitlines() if line.strip()}
    assert set(SETTINGS.codex_disable_features) <= names


def test_model_and_effort_exist() -> None:
    """The configured model is in the catalog and supports the configured reasoning effort."""
    models = {m["slug"]: m for m in json.loads(_codex("debug", "models"))["models"]}
    model = models[SETTINGS.codex_model]
    assert SETTINGS.codex_reasoning_effort in {lvl["effort"] for lvl in model["supported_reasoning_levels"]}
