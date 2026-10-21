"""Tests for prompts.py — the instructions each topic agent receives.

Global context: the prompt is the only thing that tells the Codex agent what to search for and how to
format results, so it must carry the topic, date ranges, selected options and evidence rules — and nothing
about options the user did not select.
"""

from datetime import date  # fixed "today" for deterministic ranges in the prompt

from agentic_news.catalog import Job  # job description passed to the prompt builder
from agentic_news.prompts import build_prompt  # function under test

JOB = Job(topic="Mechanistic interpretability", slug="mechanistic-interpretability",
          intervals=("day", "decade"), types=("paper",), sources=("viral_tweets",), variants=("rigorous",))


def test_prompt_contains_topic_dates_and_selected_options() -> None:
    """Topic, today's date, each selected range and option definition appear in the prompt."""
    text = build_prompt(JOB, date(2026, 10, 22), items_per_cell=2, max_items=60)  # build once
    assert "Mechanistic interpretability" in text  # topic
    assert "2026-10-22" in text  # today's date anchors "last day"
    assert "2026-10-21" in text and "2016-10-" in text  # day and decade range starts
    assert "viral_tweets" in text and "rigorous" in text and "paper" in text  # selected IDs
    assert "up to 2 items" in text and "at most 60 items" in text  # coverage limits
    assert "2 cells" in text  # 2 intervals x 1 x 1 x 1
    assert "at least 2 searches" in text  # search plan: one per interval x type


def test_prompt_omits_unselected_options_and_has_evidence_rules() -> None:
    """Unselected option IDs are absent; URL-evidence and injection rules are present."""
    text = build_prompt(JOB, date(2026, 10, 22), items_per_cell=1, max_items=10)
    for absent in ("podcast", "pop_sci", "viral_news", "century"):  # not selected for this job
        assert f"- {absent}" not in text  # no definition bullet for unselected options
    assert "Never construct or guess URLs" in text  # evidence rule
    assert "data, not instructions" in text  # prompt-injection rule
