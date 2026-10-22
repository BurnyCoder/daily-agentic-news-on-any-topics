"""Tests for catalog.py — dynamic dimensions, rules -> cells, and batching cells into agent jobs.

Global context: every combination of one option per dimension is one cell; rules select cells; build_jobs
merges the dimensions the user chose into one agent and splits the rest into separate agents.
"""

from dataclasses import replace  # derive modified dimensions in tests
from datetime import date  # fixed "today" for interval ranges

from agentic_news.catalog import (  # module under test
    DEFAULT_TOPICS,
    Dimension,
    Option,
    build_jobs,
    default_dimensions,
    default_rules,
    expand_rules,
    interval_ranges,
    rename_keys,
    slugify,
    sync_rules,
    unique_name,
    validate_dimensions,
)

DIMS = default_dimensions()
REGION = Dimension(key="region", label="Region", description="where the item is from",
                   options=(Option("eu", "Europe"), Option("us", "United States")))


def _rule(**values: list[str]) -> dict:
    """Checked rule with one id per dimension unless overridden."""
    base = {"run": True, "topic": ["physics"], "interval": ["day"], "type": ["paper"], "source": ["viral_news"],
            "variant": ["rigorous"]}
    return {**base, **values}


def test_default_dimensions_match_the_spec() -> None:
    """Five dimensions in order; 24 topics; interval options carry days."""
    assert [d.key for d in DIMS] == ["topic", "interval", "type", "source", "variant"]
    assert len(DIMS[0].options) == 24 == len(DEFAULT_TOPICS) and DIMS[0].options[0].id == "ai-industry"
    assert [o.id for o in DIMS[1].options] == ["day", "week", "month", "year", "decade", "century"]
    assert DIMS[1].kind == "interval" and DIMS[1].options[-1].days == 36524
    assert validate_dimensions(DIMS) == []


def test_validation_catches_bad_dimensions() -> None:
    """Empty, duplicate, reserved and double-interval dimensions are reported."""
    bad = [replace(DIMS[0], options=()), replace(DIMS[1], key="title"), DIMS[1], replace(REGION, key="interval")]
    errors = " ".join(validate_dimensions(bad))
    assert "no entries" in errors and "reserved" in errors and "duplicate" in errors
    assert validate_dimensions([DIMS[1], replace(DIMS[1], key="when")])  # two interval dimensions
    assert validate_dimensions([])  # at least one dimension


def test_rules_expand_to_unique_cells_in_canonical_order() -> None:
    """Union of checked rules' products; unknown ids and unchecked rules ignored; duplicates removed."""
    rules = [_rule(interval=["week", "day", "bogus"]), _rule(), {**_rule(type=["book"]), "run": False}]
    cells = expand_rules(rules, DIMS)
    assert cells == [("physics", "day", "paper", "viral_news", "rigorous"),
                     ("physics", "week", "paper", "viral_news", "rigorous")]


def test_default_and_synced_rules_follow_dimensions() -> None:
    """Seed = one unchecked rule per first-dimension entry; sync adds new dims/entries and drops removed ones."""
    rules = default_rules(DIMS)
    assert len(rules) == 24 and not rules[0]["run"] and rules[0]["topic"] == ["ai-industry"]
    assert rules[0]["interval"] == [o.id for o in DIMS[1].options]
    topics = replace(DIMS[0], options=DIMS[0].options[1:] + (Option("my-topic", "My topic"),))  # drop + add
    synced = sync_rules(rules, [topics, *DIMS[1:], REGION])
    assert ["ai-industry"] not in [r["topic"] for r in synced] and synced[-1]["topic"] == ["my-topic"]
    assert all(r["region"] == ["eu", "us"] for r in synced)  # new dimension starts fully selected


def test_all_stays_all_when_entries_are_added() -> None:
    """Rules that selected every entry of a dimension also get its new entries; partial selections stay partial."""
    empty = replace(REGION, options=())  # a dimension added from the UI starts empty
    rules = sync_rules([{**_rule(), "region": []}, {**_rule(), "interval": ["day"]}], [*DIMS, empty])
    grown_interval = replace(DIMS[1], options=DIMS[1].options + (Option("fortnight", "Last 2 weeks", "", 14),))
    synced = sync_rules(rules, [DIMS[0], grown_interval, *DIMS[2:], REGION], previous=[*DIMS, empty])
    assert [r["region"] for r in synced[:2]] == [["eu", "us"], ["eu", "us"]]  # empty-before = all-before
    assert synced[0]["interval"] == ["day"] and synced[1]["interval"] == ["day"]  # partial stays partial
    full = sync_rules([_rule(interval=[o.id for o in DIMS[1].options])], [DIMS[0], grown_interval, *DIMS[2:]],
                      previous=DIMS)
    assert full[0]["interval"][-1] == "fortnight"  # had all intervals -> gets the new one


def test_build_jobs_split_merge_and_cap() -> None:
    """No merge = one agent per cell; merged dims share an agent; the cap splits big groups."""
    cells = expand_rules([_rule(topic=["physics", "pure-math"], interval=["day", "week"], type=["paper", "book"])],
                         DIMS)  # 2 x 2 x 2 = 8 cells
    assert len(build_jobs(cells, DIMS, merge=[], max_cells=0)) == 8
    per_topic = build_jobs(cells, DIMS, merge=["interval", "type", "source", "variant"], max_cells=0)
    assert [(j.label, len(j.cells)) for j in per_topic] == [("Physics", 4), ("Pure math", 4)]
    assert per_topic[0].is_product and per_topic[0].values(1) == ("day", "week")
    capped = build_jobs(cells, DIMS, merge=["topic", "interval", "type", "source", "variant"], max_cells=3)
    assert [len(j.cells) for j in capped] == [3, 3, 2] and capped[0].label == "all cells (part 1/3)"
    assert len({j.slug for j in capped}) == 3  # unique folder names


def test_custom_dimension_and_interval_ranges() -> None:
    """A sixth dimension multiplies cells; interval ranges use each option's days."""
    dims = [*DIMS, REGION]
    cells = expand_rules([{**_rule(), "region": ["eu", "us"]}], dims)
    assert cells[-1] == ("physics", "day", "paper", "viral_news", "rigorous", "us") and len(cells) == 2
    custom = replace(DIMS[1], options=(Option("fortnight", "Last 2 weeks", "", 14),))
    assert interval_ranges(date(2026, 10, 22), custom, ("fortnight",)) == {
        "fortnight": (date(2026, 10, 8), date(2026, 10, 22))}
    assert slugify("AI & Math!") == "ai-math"


def test_unique_names_and_key_renames() -> None:
    """Names get numeric suffixes until free; renaming a dimension key carries rules and merge along."""
    assert unique_name("eu", set()) == "eu" and unique_name("eu", {"eu", "eu-2"}) == "eu-3"
    assert unique_name("region", {"region"}, sep="_") == "region_2"
    rules, merge = rename_keys([_rule(variant=["pop_sci"])], ["variant", "type"], {"variant": "level"})
    assert rules[0]["level"] == ["pop_sci"] and "variant" not in rules[0] and merge == ["level", "type"]
    assert validate_dimensions([replace(DIMS[0], key="topic_label")])  # would collide with the label column
