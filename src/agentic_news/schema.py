"""Output contract: the JSON Schema for `codex exec --output-schema`, and parsing of the agent's final answer.

Local: `build_output_schema` emits one enum field per (user-editable) dimension plus fixed text fields, in the
subset accepted by OpenAI strict Structured Outputs (object root, every property required,
`additionalProperties: false`, no length/format keywords —
https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas); Codex exec sends it with
strict=true. Per-dimension enums allow combinations outside an irregular batch, so `parse_final` drops items
whose cell is not in the batch. It also re-validates in Python (the fallback answer — the last agent_message,
used when no -o file was written — is not guaranteed to match the schema), drops unsafe links and duplicates,
re-files mis-dated items (interval dimension only, and only onto cells of the batch) and adds metadata.
Global context: rows returned here, one per item and each in exactly one cell, feed the dashboard's results.
"""

import json  # decode the agent's final message
from datetime import date  # today's date for the in_interval check
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit  # URL scheme check + normalization

from jsonschema import ValidationError, validate  # Python-side validation of the decoded answer

from agentic_news.catalog import Dimension, Job, interval_index, interval_ranges  # dimensions + batch

TEXT_FIELDS = {  # free-text item fields -> description shown to the model inside the schema
    "title": "Title of the paper, article, book, video or podcast episode",
    "url": "URL of the page actually found via web search",
    "published": "Publication date: YYYY-MM-DD, YYYY-MM, YYYY or unknown",
    "creator": "Authors, outlet or channel",
    "summary": "1-2 sentence summary",
    "why_notable": "Concrete evidence of significance or virality",
}
META_FIELDS = ["in_interval", "url_seen", "agent", "run_id"]  # added by Python, never by the model


def result_columns(dims: list[Dimension]) -> list[str]:
    """Column order of results.json/.csv: dimension ids, their readable labels, item text, metadata."""
    return [d.key for d in dims] + [f"{d.key}_label" for d in dims] + list(TEXT_FIELDS) + META_FIELDS


def build_output_schema(job: Job, dims: list[Dimension]) -> dict:
    """Strict-mode-compatible schema; each dimension field is an enum of this job's option ids."""
    item_props = {d.key: {"type": "string", "enum": list(job.values(i)), "description": d.label}
                  for i, d in enumerate(dims)}
    item_props |= {name: {"type": "string", "description": desc} for name, desc in TEXT_FIELDS.items()}
    item = {"type": "object", "properties": item_props, "required": list(item_props), "additionalProperties": False}
    return {
        "type": "object",
        "properties": {"items": {"type": "array", "items": item},
                       "coverage_notes": {"type": "string", "description": "Empty cells and why"}},
        "required": ["items", "coverage_notes"],
        "additionalProperties": False,
    }


def normalize_url(url: str) -> str:
    """Comparison key for links: lowercase, no fragment, no trailing slash, no utm_* tracking parameters."""
    parts = urlsplit(url.strip().lower())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.startswith("utm_")])
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), query, ""))


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


def _check_dates(cell: list[str], published: str, job: Job, dims: list[Dimension], today: date,
                 cells: set) -> bool | None:
    """Date check on the interval dimension; re-file in place (cell list) to the narrowest fitting selected cell."""
    iv = interval_index(dims)
    if iv is None:
        return None  # no interval dimension -> dates are not judged
    ranges = interval_ranges(today, dims[iv], job.values(iv))
    in_range = _in_interval(published, *ranges[cell[iv]])
    if in_range is False:
        for oid in sorted(job.values(iv), key=lambda i: dims[iv].option(i).days):  # narrowest first
            candidate = (*cell[:iv], oid, *cell[iv + 1:])
            if candidate in cells and _in_interval(published, *ranges[oid]):
                cell[iv] = oid
                return True
    return in_range


def parse_final(text: str, job: Job, dims: list[Dimension], run_id: str, today: date,
                seen_urls: set[str] | None = None) -> tuple[list[dict], str, int]:
    """Validate the final JSON; return (rows, coverage_notes, items dropped as off-grid). ValueError if invalid.

    seen_urls: URLs that appeared in this agent's web_search events; rows get url_seen=True when their link was
    among them (a link the model only "remembered" may still be real, but is unverified).
    """
    try:
        data = json.loads(text)
        validate(data, build_output_schema(job, dims))  # same schema the model was constrained by
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"invalid agent answer: {exc}") from exc
    cells, seen_keys = set(job.cells), {normalize_url(u) for u in seen_urls or ()}
    rows, keys, dropped = [], set(), 0
    for item in data["items"]:
        url, key = item["url"].strip(), normalize_url(item["url"])
        if urlsplit(url).scheme not in ("http", "https") or key in keys:
            continue  # drop javascript:/file: links and duplicates
        cell = [item[d.key] for d in dims]
        in_range = _check_dates(cell, item["published"], job, dims, today, cells)
        if tuple(cell) not in cells:
            dropped += 1  # a combination this agent was not asked for
            continue
        keys.add(key)
        rows.append({**dict(zip([d.key for d in dims], cell)),
                     **{f"{d.key}_label": d.option(v).label for d, v in zip(dims, cell)},  # readable in the CSV
                     **{f: item[f] for f in TEXT_FIELDS}, "url": url,
                     "in_interval": in_range, "url_seen": key in seen_keys, "agent": job.slug, "run_id": run_id})
    return rows, data["coverage_notes"], dropped
