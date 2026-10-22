"""Tests for app.py + dashboard sections with Streamlit's headless AppTest
(https://docs.streamlit.io/develop/api-reference/app-testing).

Global context: renders the real dashboard against temporary folders; launching is monkeypatched so no
background process starts here (test_launcher.py covers that path).
"""

from dataclasses import replace  # custom dimension / overrides
from pathlib import Path  # project root + temporary folders

import pytest  # monkeypatch
from streamlit.testing.v1 import AppTest  # headless Streamlit runner

import agentic_news.launcher  # patched launch_run
from agentic_news.catalog import Dimension, Option  # custom dimension
from agentic_news.config import config_to_dict  # seed workspace/run files
from agentic_news.store import read_json, write_json  # seed and inspect files
from conftest import make_config  # small configs

APP = str(Path(__file__).resolve().parents[1] / "app.py")
REGION = Dimension("region", "Region", "where it comes from", "category", (Option("eu", "Europe"), Option("us", "USA")))


def _app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=30).run()


def _markdown(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def test_first_start_has_defaults_and_nothing_to_run(fake_env: Path) -> None:
    """Fresh install: default workspace saved, 0 cells, Get News disabled."""
    at = _app()
    assert not at.exception
    assert "**0** cell(s) selected" in _markdown(at) and at.button(key="get_news").disabled
    assert [d["key"] for d in read_json(fake_env / "data" / "workspace.json")["dimensions"]][:2] == ["topic", "interval"]


def test_custom_dimension_flows_to_preview_and_launch(fake_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 6th dimension doubles the cells; no merge -> one agent per cell; Get News hands the config over."""
    cfg = make_config("Physics", merge=[])
    cfg = replace(cfg, dimensions=[*cfg.dimensions, REGION], rules=[{**cfg.rules[0], "region": ["eu", "us"]}])
    write_json(fake_env / "data" / "workspace.json", config_to_dict(cfg))
    launched = []
    monkeypatch.setattr(agentic_news.launcher, "launch_run", lambda c, s: launched.append(c) or "x")
    at = _app()
    assert "**2** cell(s) → **2** agent(s)" in _markdown(at) and not at.button(key="get_news").disabled
    at.button(key="get_news").click().run()
    assert launched and launched[0].dimensions[-1].key == "region"


def test_confirmation_threshold_blocks_big_launches(fake_env: Path) -> None:
    """Above the threshold, Get News stays disabled until the confirmation box is ticked."""
    cfg = make_config("Physics", "LLMs", "Agents", merge=[], overrides={"confirm_above_agents": 2})
    write_json(fake_env / "data" / "workspace.json", config_to_dict(cfg))
    at = _app()
    assert at.button(key="get_news").disabled
    next(c for c in at.checkbox if c.label.startswith("Yes, launch 3 agents")).check().run()
    assert not at.button(key="get_news").disabled


def test_add_dimension_from_the_ui(fake_env: Path) -> None:
    """The add-dimension form creates a new (still empty, so flagged) dimension in the saved workspace."""
    at = _app()
    next(t for t in at.text_input if t.label == "Label").set_value("Audience level")
    next(b for b in at.button if b.label == "Add dimension").click().run()
    keys = [d["key"] for d in read_json(fake_env / "data" / "workspace.json")["dimensions"]]
    assert keys[-1] == "audience_level" and any("has no entries" in e.value for e in at.error)


def test_results_grid_and_items_of_a_finished_run(fake_env: Path) -> None:
    """A finished run shows the cell grid (zeros included) and its items with readable labels."""
    run_dir = fake_env / "runs" / "20261022-090000"
    cfg = make_config("Physics", intervals=("day", "week", "decade"))
    write_json(run_dir / "config.json", config_to_dict(cfg))
    write_json(run_dir / "status.json", {"run_id": "20261022-090000", "state": "done", "pid": 0, "agents": {}})
    write_json(run_dir / "results.json", [{"topic": "physics", "interval": "day", "type": "paper",
                                           "source": "viral_news", "variant": "rigorous", "title": "T",
                                           "url": "https://x.org", "published": "2026-10-21", "creator": "C",
                                           "summary": "S", "why_notable": "W", "in_interval": True,
                                           "url_seen": True, "agent": "physics", "run_id": "20261022-090000"}])
    at = _app()
    assert not at.exception
    grid = next(d.value for d in at.dataframe if "Last week" in d.value.columns)
    assert grid.loc["Physics", "Last day"] == 1 and grid.loc["Physics", "Last week"] == 0
    assert list(grid.columns) == ["Last day", "Last week", "Last 10 years"]  # entry order, not alphabetical
    items = next(d.value for d in at.dataframe if "title" in d.value.columns)
    assert items.iloc[0]["title"] == "T" and items.iloc[0]["interval"] == "Last day"


def test_bulk_edit_leaves_topics_alone_by_default(fake_env: Path) -> None:
    """Applying bulk entries changes the chosen dimensions of checked rows; the topic column stays per row."""
    write_json(fake_env / "data" / "workspace.json", config_to_dict(make_config("Physics", "LLMs")))
    at = _app()
    at.multiselect(key="bulk_interval").set_value(["week"])
    next(b for b in at.button if b.label == "Apply entries to checked rows").click().run()
    rules = read_json(fake_env / "data" / "workspace.json")["rules"]
    assert [(r["topic"], r["interval"]) for r in rules] == [(["physics"], ["week"]), (["llms"], ["week"])]


def test_merge_choice_changes_the_agent_count(fake_env: Path) -> None:
    """Choosing dimensions to merge in the UI regroups the same cells into fewer agents and is saved."""
    write_json(fake_env / "data" / "workspace.json", config_to_dict(make_config("Physics", intervals=("day", "week"),
                                                                                merge=[])))
    at = _app()
    assert "**2** cell(s) → **2** agent(s)" in _markdown(at)
    at.multiselect(key="merge").set_value(["interval"]).run()
    assert "**2** cell(s) → **1** agent(s)" in _markdown(at)
    assert read_json(fake_env / "data" / "workspace.json")["merge"] == ["interval"]


def test_agents_section_shows_live_status(fake_env: Path) -> None:
    """The Agents section lists each agent's label, state and counters from status.json."""
    run_dir = fake_env / "runs" / "20261022-100000"
    write_json(run_dir / "status.json", {"run_id": "20261022-100000", "state": "done", "pid": 0, "started": "t",
                                         "agents": {"physics": {"label": "Physics · Last day", "cells": 2,
                                                                "state": "done", "attempt": 1, "searches": 3,
                                                                "items": 2, "dropped": 1, "input_tokens": 10,
                                                                "output_tokens": 5, "last_event": "turn completed",
                                                                "error": ""}}})
    at = _app()
    assert "1/1 agents finished" in _markdown(at)
    table = next(d.value for d in at.dataframe if "agent" in d.value.columns)
    assert table.iloc[0]["agent"] == "Physics · Last day" and table.iloc[0]["off-grid dropped"] == 1


def test_adding_a_dimension_twice_keeps_keys_unique(fake_env: Path) -> None:
    """A second dimension with the same label gets a suffixed key instead of a duplicate."""
    at = _app()
    for _ in range(2):
        next(t for t in at.text_input if t.label == "Label").set_value("Region")
        next(b for b in at.button if b.label == "Add dimension").click().run()
    keys = [d["key"] for d in read_json(fake_env / "data" / "workspace.json")["dimensions"]]
    assert keys[-2:] == ["region", "region_2"]
