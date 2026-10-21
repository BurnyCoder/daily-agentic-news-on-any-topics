"""Tests for schema.py — the JSON Schema passed to `codex exec --output-schema` and parsing of the answer.

Global context: Codex sends the schema in OpenAI strict Structured Outputs mode, which only accepts a
subset of JSON Schema (https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas);
an incompatible schema makes every agent fail, so the strict rules are checked here without spending tokens.
"""

import json  # build agent answers as JSON text
from datetime import date  # fixed "today" for the in_interval check

import pytest  # raises() for invalid answers
from jsonschema import Draft202012Validator  # meta-schema check of the generated schema

from agentic_news.catalog import Job  # job whose selection becomes the enums
from agentic_news.schema import build_output_schema, parse_final  # functions under test

JOB = Job(topic="Physics", slug="physics", intervals=("day", "year"), types=("paper", "video"),
          sources=("viral_news",), variants=("pop_sci", "rigorous"))
TODAY = date(2026, 10, 22)
BANNED = {"minLength", "maxLength", "minItems", "maxItems", "format", "pattern"}  # risky in strict mode


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
    base = {"interval": "day", "type": "paper", "source": "viral_news", "variant": "rigorous",
            "title": "T", "url": "https://arxiv.org/abs/2610.00001", "published": "2026-10-21",
            "creator": "A. Author", "summary": "S", "why_notable": "1k HN points"}
    return {**base, **overrides}


def test_schema_is_valid_and_strict_compatible() -> None:
    """Valid JSON Schema, strict-compatible, enums equal to the job's selection."""
    schema = build_output_schema(JOB)
    Draft202012Validator.check_schema(schema)  # valid against the JSON Schema meta-schema
    assert schema["type"] == "object"  # strict mode needs an object root
    _assert_strict(schema)
    props = schema["properties"]["items"]["items"]["properties"]
    assert props["interval"]["enum"] == ["day", "year"] and props["type"]["enum"] == ["paper", "video"]


def test_parse_final_adds_metadata_filters_and_flags_dates() -> None:
    """Valid answers become rows; non-http links and duplicate URLs are dropped; dates are checked."""
    answer = {"coverage_notes": "no videos", "items": [
        _item(),
        _item(title="dup", url="https://arxiv.org/abs/2610.00001/"),  # same URL with trailing slash
        _item(url="javascript:alert(1)"),  # unsafe link
        _item(interval="day", published="2020-01-01", url="https://example.org/old"),  # outside last day
        _item(interval="year", published="2026-03", url="https://example.org/month"),  # month precision
        _item(published="unknown", url="https://example.org/unknown"),
    ]}
    rows, notes = parse_final(json.dumps(answer), JOB, run_id="r1", today=TODAY)
    assert notes == "no videos"
    assert [r["url"] for r in rows] == ["https://arxiv.org/abs/2610.00001", "https://example.org/old",
                                        "https://example.org/month", "https://example.org/unknown"]
    assert rows[0]["topic"] == "Physics" and rows[0]["run_id"] == "r1"  # metadata added by Python
    assert [r["in_interval"] for r in rows] == [True, False, True, None]  # date check per item


def test_parse_final_rejects_invalid_answers() -> None:
    """Malformed JSON and values outside the selection raise ValueError."""
    with pytest.raises(ValueError):
        parse_final("not json", JOB, run_id="r1", today=TODAY)  # malformed
    bad = {"coverage_notes": "", "items": [_item(interval="century")]}  # interval not selected
    with pytest.raises(ValueError):
        parse_final(json.dumps(bad), JOB, run_id="r1", today=TODAY)
