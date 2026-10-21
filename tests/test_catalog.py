"""Tests for catalog.py — dimension options, default topics and turning table rows into agent jobs.

Global context: build_jobs decides which Codex agents get launched (one per checked topic row), so
its filtering and slug rules directly control cost and output folders.
"""

from datetime import date  # fixed "today" for deterministic interval ranges

from agentic_news.catalog import (  # module under test
    DEFAULT_TOPICS,
    DIMENSIONS,
    build_jobs,
    default_rows,
    interval_ranges,
)


def test_default_topics_and_dimensions_match_the_spec() -> None:
    """The 24 requested topics and the 4 dimensions with their stable IDs are present."""
    assert len(DEFAULT_TOPICS) == 24 and "Memetic tribes in AI" in DEFAULT_TOPICS  # user's topic list
    assert list(DIMENSIONS["intervals"]) == ["day", "week", "month", "year", "decade", "century"]
    assert list(DIMENSIONS["types"]) == ["paper", "article", "book", "video", "podcast"]
    assert list(DIMENSIONS["sources"]) == ["viral_papers", "viral_news", "viral_tweets", "viral_content"]
    assert list(DIMENSIONS["variants"]) == ["pop_sci", "rigorous"]


def test_default_rows_are_unchecked_with_full_forms() -> None:
    """Seed rows: one per topic, not selected, every option pre-filled."""
    rows = default_rows()  # what the dashboard shows on first start
    assert len(rows) == 24 and not any(r["run"] for r in rows)  # nothing launches by accident
    assert rows[0]["intervals"] == list(DIMENSIONS["intervals"])  # full form by default


def test_build_jobs_filters_orders_and_counts_cells() -> None:
    """Only checked rows with a topic and non-empty dimensions become jobs; unknown values are dropped."""
    rows = [
        {"run": True, "topic": "Physics", "intervals": ["week", "day", "bogus"], "types": ["paper"],
         "sources": ["viral_news"], "variants": ["rigorous", "pop_sci"]},
        {"run": False, "topic": "Philosophy", "intervals": ["day"], "types": ["book"],
         "sources": ["viral_news"], "variants": ["pop_sci"]},  # unchecked -> skipped
        {"run": True, "topic": "  ", "intervals": ["day"], "types": ["book"],
         "sources": ["viral_news"], "variants": ["pop_sci"]},  # blank topic -> skipped
        {"run": True, "topic": "LLMs", "intervals": [], "types": ["book"],
         "sources": ["viral_news"], "variants": ["pop_sci"]},  # empty dimension -> skipped
    ]
    jobs = build_jobs(rows)  # function under test
    assert len(jobs) == 1  # only the first row survives
    job = jobs[0]
    assert job.intervals == ("day", "week")  # canonical order, unknown value dropped
    assert job.variants == ("pop_sci", "rigorous")  # canonical order
    assert job.cells == 2 * 1 * 1 * 2  # product of selected option counts
    assert job.slug == "physics"  # folder-safe name


def test_build_jobs_makes_slugs_unique() -> None:
    """Two rows whose topics slugify the same get distinct folder names."""
    row = {"run": True, "intervals": ["day"], "types": ["book"], "sources": ["viral_news"], "variants": ["pop_sci"]}
    jobs = build_jobs([{**row, "topic": "AI & Math"}, {**row, "topic": "AI  math"}])  # both -> "ai-math"
    assert [j.slug for j in jobs] == ["ai-math", "ai-math-2"]  # collision gets a numeric suffix


def test_interval_ranges_from_fixed_today() -> None:
    """Each interval maps to an inclusive (start, today) date range."""
    ranges = interval_ranges(date(2026, 10, 22), ("day", "year", "century"))  # selected intervals only
    assert ranges["day"] == (date(2026, 10, 21), date(2026, 10, 22))  # last 24 hours, as dates
    assert ranges["year"][0] == date(2025, 10, 22)  # 365 days back
    assert ranges["century"][0].year == 1926  # 100 years back
    assert set(ranges) == {"day", "year", "century"}  # unselected intervals are absent
