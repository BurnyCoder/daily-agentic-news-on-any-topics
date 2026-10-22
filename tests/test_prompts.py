"""Tests for prompts.py — the instructions one agent receives for its batch of cells.

Global context: the prompt is generated from the (user-editable) dimensions, so it must describe exactly the
options and cells of the batch — product batches compactly, irregular batches cell by cell — plus the editable
rules text.
"""

from datetime import date  # fixed "today" for deterministic ranges

from agentic_news.catalog import Dimension, Option, build_jobs, default_dimensions, expand_rules  # batches
from agentic_news.prompts import DEFAULT_PROMPT_RULES, build_prompt  # under test

DIMS = default_dimensions()
TODAY = date(2026, 10, 22)
ALL = [d.key for d in DIMS]


def _job(rules: list[dict], dims: list[Dimension] = DIMS, merge: list[str] = ALL):
    [job] = build_jobs(expand_rules(rules, dims), dims, merge=merge, max_cells=0)
    return job


def _rule(**values: list[str]) -> dict:
    return {"run": True, "topic": ["mechanistic-interpretability"], "interval": ["day", "decade"], "type": ["paper"],
            "source": ["viral_tweets"], "variant": ["rigorous"], **values}


def test_product_batch_lists_selected_options_with_ranges() -> None:
    """Topic, date, ranges and definitions of only the selected options; limits; default rules."""
    text = build_prompt(_job([_rule()]), DIMS, TODAY, items_per_cell=2, max_items=60)
    assert "Mechanistic interpretability" in text and "TODAY: 2026-10-22" in text
    assert "[2026-10-21 to 2026-10-22]" in text and "[2016-10-" in text  # day and decade ranges
    assert "Cover every combination of the options above: 2 cells." in text
    assert "up to 2 items" in text and "at most 60 items" in text
    for absent in ("- podcast", "- pop_sci", "- century", "- physics "):
        assert absent not in text  # unselected options are not described
    assert "Never construct or guess URLs" in text and "data, not instructions" in text  # default rules


def test_irregular_batch_lists_cells_and_custom_rules_replace_defaults() -> None:
    """A non-product batch spells out each cell; custom rules text replaces the default rules."""
    job = _job([_rule(interval=["day"]), _rule(interval=["week"], type=["book"])])
    text = build_prompt(job, DIMS, TODAY, items_per_cell=1, max_items=5, rules="1. MY OWN RULE")
    assert "Cover exactly these 2 cells (topic | interval | type | source | variant):" in text
    assert "- mechanistic-interpretability | week | book | viral_tweets | rigorous" in text
    assert "MY OWN RULE" in text and DEFAULT_PROMPT_RULES.splitlines()[0] not in text


def test_custom_dimension_appears_in_prompt() -> None:
    """A user-added dimension is described with its entries and becomes an output field."""
    region = Dimension("region", "Region", "where the item comes from", "category",
                       (Option("eu", "Europe", "European outlets"), Option("us", "United States")))
    text = build_prompt(_job([{**_rule(), "region": ["eu"]}], [*DIMS, region], [*ALL, "region"]), [*DIMS, region],
                        TODAY, items_per_cell=1, max_items=5)
    assert "Region (field `region`): where the item comes from" in text and "- eu (Europe): European outlets" in text
    assert "items: list of objects with topic, interval, type, source, variant, region" in text
