"""Tests for events.py — rendering `codex exec --json` events for the log and counting them for the status.

Global context: fixtures/events_sample.jsonl starts with a real event stream captured from codex-cli 0.163.0
(gpt-6-luna, live web search) followed by synthetic events of other documented types
(https://learn.chatgpt.com/docs/non-interactive-mode), so the renderer is grounded in the actual format.
"""

import json  # decode fixture lines
from pathlib import Path  # fixture location

from agentic_news.events import apply_event, describe_event, is_fatal_error, new_counters, search_urls  # under test

EVENTS = [json.loads(line) for line in (Path(__file__).parent / "fixtures" / "events_sample.jsonl")
          .read_text(encoding="utf-8").splitlines()]


def test_describe_renders_every_important_event_in_full() -> None:
    """Searches, messages, reasoning, commands, errors and unknown events all produce full log text."""
    text = "\n".join(t for t in map(describe_event, EVENTS) if t)  # what the log will contain
    assert '"url": "https://news.ycombinator.com"' in text  # web search action from the real stream
    assert "Railway Security Disclosure" in text  # agent's final message text
    assert "Checking the HN front page" in text  # reasoning summary
    assert "$ curl -s https://example.org" in text and "<html>ok</html>" in text  # command + full output
    assert "TURN FAILED: You've hit your usage limit." in text  # failure reason
    assert "some.future.event" in text  # unknown event types are not silently dropped
    assert '"output_tokens": 77' in text  # token usage line


def test_long_text_is_not_truncated() -> None:
    """A 100 KB agent message is rendered completely."""
    big = "y" * 100_000
    out = describe_event({"type": "item.completed", "item": {"type": "agent_message", "text": big}})
    assert out is not None and big in out


def test_search_urls_collects_opened_pages_and_results() -> None:
    """URLs come from completed web_search items: the opened page and every result."""
    urls = [u for e in EVENTS for u in search_urls(e)]
    assert urls == ["https://news.ycombinator.com", "https://news.ycombinator.com/"]  # action.url + results[].url


def test_counters_and_fatal_errors() -> None:
    """Counters add up over the stream; usage-limit/auth errors are classified as fatal."""
    counters = new_counters()
    for event in EVENTS:
        apply_event(counters, event)
    assert counters["searches"] == 1 and counters["commands"] == 1  # completed items only
    assert counters["input_tokens"] == 36192 and counters["output_tokens"] == 77  # from turn.completed
    assert counters["error"] == "You've hit your usage limit."  # last error wins
    assert is_fatal_error(counters["error"]) and is_fatal_error("401 Unauthorized")
    assert not is_fatal_error("stream disconnected before completion")  # transient -> retry allowed
