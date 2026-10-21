"""Output contract: the JSON Schema for `codex exec --output-schema`, and parsing of the agent's final answer.

Local: `build_output_schema` emits a schema in the subset accepted by OpenAI strict Structured Outputs
(object root, every property required, `additionalProperties: false`, no length/format keywords —
https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas); Codex exec sends it with
strict=true. `parse_final` re-validates in Python (the model can still emit malformed JSON,
https://github.com/openai/codex/issues/50127), drops unsafe links and duplicates, and adds metadata.
Global context: rows returned here are what the dashboard's results table shows.
"""

import json  # decode the agent's final message
from datetime import date  # today's date for the in_interval check
from urllib.parse import urlparse  # scheme check: only http(s) links reach the clickable table

from jsonschema import ValidationError, validate  # Python-side validation of the decoded answer

from agentic_news.catalog import ITEM_FIELD, Job, interval_ranges  # enums come from the job's selection

TEXT_FIELDS = {  # free-text item fields -> description shown to the model inside the schema
    "title": "Title of the paper, article, book, video or podcast episode",
    "url": "URL of the page actually found via web search",
    "published": "Publication date: YYYY-MM-DD, YYYY-MM, YYYY or unknown",
    "creator": "Authors, outlet or channel",
    "summary": "1-2 sentence summary",
    "why_notable": "Concrete evidence of significance or virality",
}


def build_output_schema(job: Job) -> dict:
    """Strict-mode-compatible schema whose dimension enums are limited to this job's selection."""
    item_props = {field: {"type": "string", "enum": list(getattr(job, dim))} for dim, field in ITEM_FIELD.items()}
    item_props |= {name: {"type": "string", "description": desc} for name, desc in TEXT_FIELDS.items()}
    item = {"type": "object", "properties": item_props, "required": list(item_props), "additionalProperties": False}
    return {
        "type": "object",
        "properties": {"items": {"type": "array", "items": item},
                       "coverage_notes": {"type": "string", "description": "Empty cells and why"}},
        "required": ["items", "coverage_notes"],
        "additionalProperties": False,
    }


def _in_interval(published: str, start: date, end: date) -> bool | None:
    """Does a YYYY-MM-DD / YYYY-MM / YYYY date overlap [start, end]? None when unparseable or 'unknown'."""
    parts = published.strip().split("-")
    try:
        nums = [int(p) for p in parts]
        lo = date(nums[0], nums[1] if len(nums) > 1 else 1, nums[2] if len(nums) > 2 else 1)  # period start
        hi = date(nums[0], nums[1] if len(nums) > 1 else 12, nums[2] if len(nums) > 2 else 28)  # ~period end
    except (ValueError, IndexError):
        return None  # "unknown" or free text
    return lo <= end and hi >= start  # overlap test: partial dates count if any part falls in range


def parse_final(text: str, job: Job, run_id: str, today: date) -> tuple[list[dict], str]:
    """Validate the final JSON and return (rows, coverage_notes); raise ValueError if invalid."""
    try:
        data = json.loads(text)
        validate(data, build_output_schema(job))  # same schema the model was constrained by
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"invalid agent answer: {exc}") from exc
    ranges = interval_ranges(today, job.intervals)
    rows, seen = [], set()
    for item in data["items"]:
        url = item["url"].strip()
        key = url.rstrip("/").lower()  # trailing slash / case variants are the same link
        if urlparse(url).scheme not in ("http", "https") or key in seen:
            continue  # drop javascript:/file: links and duplicates
        seen.add(key)
        in_range = _in_interval(item["published"], *ranges[item["interval"]])
        rows.append({"topic": job.topic, **item, "url": url, "in_interval": in_range, "run_id": run_id})
    return rows, data["coverage_notes"]
