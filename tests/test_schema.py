"""Tests for schema.py — the JSON Schema passed to `codex exec --output-schema` and parsing of the answer.

Global context: Codex sends the schema in OpenAI strict Structured Outputs mode, which only accepts a
subset of JSON Schema (https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas);
an incompatible schema makes every agent fail, so the strict rules are checked here without spending tokens.
The schema and parsing are generated from the user-editable dimensions.
"""

import json  # build agent answers as JSON text
from datetime import date  # fixed "today" for the in_interval check

import pytest  # raises() for invalid answers
from jsonschema import Draft202012Validator  # meta-schema check of the generated schema

from agentic_news.catalog import Dimension, Option, build_jobs, default_dimensions, expand_rules  # batches
from agentic_news.schema import build_output_schema, parse_final, result_columns  # under test

DIMS = default_dimensions()
ALL = [d.key for d in DIMS]
TODAY = date(2026, 10, 22)
BANNED = {"minLength", "maxLength", "minItems", "maxItems", "format", "pattern"}  # risky in strict mode
RULE = {"run": True, "topic": ["physics"], "interval": ["day", "year"], "type": ["paper", "video"],
        "source": ["viral_news"], "variant": ["pop_sci", "rigorous"]}
[JOB] = build_jobs(expand_rules([RULE], DIMS), DIMS, merge=ALL, max_cells=0)  # 2 x 2 x 1 x 2 = 8 cells


def _assert_strict(node: dict) -> None:
    """Recursively check the strict-mode rules: closed objects, every property required, no banned keywords."""
    assert not BANNED & set(node)  # no length/format constraints
    if node.get("type") == "object":
        assert node["additionalProperties"] is False  # strict mode requires closed objects
        assert set(node["required"]) == set(node["properties"])  # every property must be required
        for child in node["properties"].values():
            _assert_strict(child)
    if node.get("type") == "array":
        _assert_strict(node["items"])


def _item(**overrides: str) -> dict:
    """A valid item; overrides change single fields."""
    base = {"topic": "physics", "interval": "day", "type": "paper", "source": "viral_news", "variant": "rigorous",
            "title": "T", "url": "https://arxiv.org/abs/2610.00001", "published": "2026-10-21",
            "creator": "A. Author", "summary": "S", "why_notable": "1k HN points"}
    return {**base, **overrides}


def _answer(*items: dict) -> str:
    return json.dumps({"coverage_notes": "notes", "items": list(items)})


def test_schema_is_valid_strict_and_generated_from_dimensions() -> None:
    """Valid JSON Schema, strict-compatible, one enum per dimension equal to the job's values."""
    schema = build_output_schema(JOB, DIMS)
    Draft202012Validator.check_schema(schema)
    assert schema["type"] == "object"
    _assert_strict(schema)
    props = schema["properties"]["items"]["items"]["properties"]
    assert props["topic"]["enum"] == ["physics"] and props["interval"]["enum"] == ["day", "year"]
    assert list(props)[:5] == ALL
    assert result_columns(DIMS)[:11] == [*ALL, *[f"{k}_label" for k in ALL], "title"]  # ids, labels, item fields


def test_parse_final_adds_metadata_filters_and_flags_dates() -> None:
    """Rows keep dimension ids; unsafe/duplicate links dropped; mis-dated items re-filed; flags set."""
    answer = _answer(
        _item(url="https://arxiv.org/abs/2610.00001?utm_source=x"),
        _item(title="dup", url="https://arxiv.org/abs/2610.00001/"),  # same URL without tracking/with slash
        _item(url="javascript:alert(1)"),  # unsafe link
        _item(published="2026-03-02", url="https://example.org/refile"),  # fits "year" instead of "day"
        _item(published="2020-01-01", url="https://example.org/old"),  # fits no selected interval
        _item(interval="year", published="2026-03", url="https://example.org/month"),  # month precision
        _item(published="unknown", url="https://example.org/unknown"),
    )
    seen = {"https://arxiv.org/abs/2610.00001", "https://example.org/month/"}  # URLs from search results
    rows, notes, dropped = parse_final(answer, JOB, DIMS, run_id="r1", today=TODAY, seen_urls=seen)
    assert notes == "notes" and dropped == 0
    assert [r["url"] for r in rows] == ["https://arxiv.org/abs/2610.00001?utm_source=x", "https://example.org/refile",
                                        "https://example.org/old", "https://example.org/month",
                                        "https://example.org/unknown"]
    assert rows[0]["topic"] == "physics" and rows[0]["run_id"] == "r1" and rows[0]["agent"] == JOB.slug
    assert rows[0]["topic_label"] == "Physics" and rows[1]["interval_label"] == "Last year"  # readable labels
    assert [r["interval"] for r in rows] == ["day", "year", "day", "year", "day"]
    assert [r["in_interval"] for r in rows] == [True, True, False, True, None]
    assert [r["url_seen"] for r in rows] == [True, False, False, True, False]


def test_off_grid_items_are_dropped_and_refiling_stays_on_grid() -> None:
    """In an irregular batch, items in unselected cells are dropped, and re-filing only targets selected cells."""
    rules = [{**RULE, "interval": ["day"], "type": ["paper"], "variant": ["rigorous"]},
             {**RULE, "interval": ["year"], "type": ["video"], "variant": ["rigorous"]}]
    [job] = build_jobs(expand_rules(rules, DIMS), DIMS, merge=ALL, max_cells=0)  # 2 cells, not a product
    answer = _answer(_item(),  # (day, paper) selected
                     _item(type="video", url="https://example.org/v-day"),  # (day, video) not selected -> dropped
                     _item(published="2026-03-02", url="https://example.org/p"))  # would re-file to (year, paper): off grid
    rows, _, dropped = parse_final(answer, job, DIMS, run_id="r1", today=TODAY)
    assert [r["url"] for r in rows] == ["https://arxiv.org/abs/2610.00001", "https://example.org/p"]
    assert rows[1]["interval"] == "day" and rows[1]["in_interval"] is False and dropped == 1


def test_custom_dimension_and_no_interval_dimension() -> None:
    """A user dimension becomes a schema/result field; without an interval dimension dates are not judged."""
    region = Dimension("region", "Region", "", "category", (Option("eu", "Europe"),))
    dims = [d for d in DIMS if d.kind != "interval"] + [region]
    rule = {k: v for k, v in RULE.items() if k != "interval"} | {"region": ["eu"]}
    [job] = build_jobs(expand_rules([rule], dims), dims, merge=[d.key for d in dims], max_cells=0)
    assert build_output_schema(job, dims)["properties"]["items"]["items"]["properties"]["region"]["enum"] == ["eu"]
    item = {k: v for k, v in _item().items() if k != "interval"} | {"region": "eu", "published": "1900"}
    rows, _, _ = parse_final(_answer(item), job, dims, run_id="r1", today=TODAY)
    assert rows[0]["region"] == "eu" and rows[0]["in_interval"] is None


def test_parse_final_rejects_invalid_answers() -> None:
    """Malformed JSON and values outside the batch raise ValueError."""
    with pytest.raises(ValueError):
        parse_final("not json", JOB, DIMS, run_id="r1", today=TODAY)
    with pytest.raises(ValueError):
        parse_final(_answer(_item(interval="century")), JOB, DIMS, run_id="r1", today=TODAY)
