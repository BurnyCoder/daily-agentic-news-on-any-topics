"""Codex event handling: render `codex exec --json` JSONL events as full log text and count them for the status.

Local: event types are thread.started, turn.started, turn.completed{usage}, turn.failed{error}, error{message}
and item.started/updated/completed{item}; item types include agent_message, reasoning, web_search
(query, action, results), command_execution (command, aggregated_output, exit_code), mcp_tool_call, ...
(https://learn.chatgpt.com/docs/non-interactive-mode; shapes checked against a real codex-cli 0.163.0 stream in
tests/fixtures/events_sample.jsonl). Unknown events are dumped as JSON instead of being dropped.
Global context: codex_runner logs `describe_event` output for every line and feeds `apply_event` into the
StatusBoard that the dashboard polls. Raw lines are also kept unmodified in events_attempt<N>.jsonl.
"""

import json  # dump structured event details without truncation
import re  # classify fatal error messages

_FATAL = re.compile(r"usage limit|unauthori[sz]ed|\b401\b|not logged in|please log ?in", re.IGNORECASE)


def _dump(data: object) -> str:
    """Full JSON text (non-ASCII kept readable)."""
    return json.dumps(data, ensure_ascii=False)


def _describe_item(phase: str, item: dict) -> str | None:
    """Log text for one item event; None for partial states whose final content arrives on completion."""
    kind = item.get("type")
    if kind == "command_execution" and phase == "started":
        return f"$ {item.get('command')}"  # show the command as soon as it starts
    if phase != "completed":
        return None  # started/updated states are repeated in full by item.completed
    if kind in ("agent_message", "reasoning"):
        return f"{kind}:\n{item.get('text', '')}"  # multi-line text printed as-is
    if kind == "command_execution":
        return (f"command finished exit={item.get('exit_code')} status={item.get('status')}:\n"
                f"{item.get('aggregated_output', '')}")
    details = {k: v for k, v in item.items() if k not in ("id", "type")}  # web_search, mcp_tool_call, ...
    return f"{kind}: {_dump(details)}"


def describe_event(event: dict) -> str | None:
    """Human-readable, untruncated log text for one event (None = nothing worth logging)."""
    kind = str(event.get("type", ""))
    if kind.startswith("item."):
        return _describe_item(kind.removeprefix("item."), event.get("item") or {})
    if kind == "thread.started":
        return f"thread started {event.get('thread_id')}"
    if kind == "turn.started":
        return "turn started"
    if kind == "turn.completed":
        return f"turn completed, usage: {_dump(event.get('usage', {}))}"
    if kind == "turn.failed":
        return f"TURN FAILED: {(event.get('error') or {}).get('message')}"
    if kind == "error":
        return f"ERROR: {event.get('message')}"
    return f"event: {_dump(event)}"  # future/unknown event types


def new_counters() -> dict:
    """Per-agent counters shown in the dashboard's status table."""
    return {"searches": 0, "commands": 0, "input_tokens": 0, "output_tokens": 0, "error": ""}


def apply_event(counters: dict, event: dict) -> None:
    """Update counters in place from one event."""
    kind = event.get("type")
    item_type = (event.get("item") or {}).get("type")
    if kind == "item.completed" and item_type == "web_search":
        counters["searches"] += 1
    elif kind == "item.completed" and item_type == "command_execution":
        counters["commands"] += 1
    elif kind == "turn.completed":
        usage = event.get("usage") or {}
        counters["input_tokens"] += usage.get("input_tokens", 0)
        counters["output_tokens"] += usage.get("output_tokens", 0)
    elif kind in ("turn.failed", "error"):
        counters["error"] = (event.get("error") or {}).get("message") or event.get("message") or ""


def is_fatal_error(message: str) -> bool:
    """Usage-limit and authentication errors: retrying would only fail again."""
    return bool(_FATAL.search(message or ""))
