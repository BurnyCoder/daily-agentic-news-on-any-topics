"""Tests for app.py with Streamlit's headless AppTest (https://docs.streamlit.io/develop/api-reference/app-testing).

Global context: renders the real dashboard script against temporary folders; launching is monkeypatched so no
background process starts here (test_launcher.py covers that path).
"""

from pathlib import Path  # project root + temporary folders

import pytest  # monkeypatch
from streamlit.testing.v1 import AppTest  # headless Streamlit runner

import agentic_news.launcher  # patched launch_run
from agentic_news.store import write_json  # seed selection/results files
from conftest import selection  # checked rows

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_first_start_shows_24_unchecked_topics(fake_env: Path) -> None:
    """Fresh install: 24 default rows, Get News disabled because nothing is checked."""
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert at.button(key="get_news").disabled  # no topic checked yet
    assert "0** topic agent(s)" in at.markdown[0].value


def test_get_news_launches_with_the_saved_selection(fake_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A saved selection with checked rows enables Get News, which hands the rows to launch_run."""
    rows = selection("Physics", "LLMs")
    write_json(fake_env / "data" / "selection.json", rows)
    launched = []
    monkeypatch.setattr(agentic_news.launcher, "launch_run", lambda r, s: launched.append(r) or "x")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.button(key="get_news").disabled
    at.button(key="get_news").click().run()
    assert launched and [r["topic"] for r in launched[0]] == ["Physics", "LLMs"]


def test_results_of_a_finished_run_are_shown(fake_env: Path) -> None:
    """A finished run's results appear in the results table with readable labels."""
    run_dir = fake_env / "runs" / "20261022-090000"
    write_json(run_dir / "status.json", {"run_id": "20261022-090000", "state": "done", "pid": 0, "agents": {}})
    write_json(run_dir / "results.json", [{"topic": "Physics", "interval": "day", "type": "paper",
                                           "source": "viral_news", "variant": "rigorous", "title": "T",
                                           "url": "https://x.org", "published": "2026-10-21", "creator": "C",
                                           "summary": "S", "why_notable": "W", "in_interval": True,
                                           "run_id": "20261022-090000"}])
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    table = next(d.value for d in at.dataframe if "title" in d.value.columns)  # the results table
    assert table.iloc[0]["title"] == "T" and table.iloc[0]["interval"] == "Last day"
