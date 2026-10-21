"""Fake `codex` executable for tests: mimics the `codex exec --json` I/O contract without calling any model.

Local: reads the prompt from stdin (as `codex exec -` does), prints JSONL events to stdout, writes the final
answer to the `--output-last-message` file, and picks a behaviour from a `MODE=<name>` line in the prompt:
ok | fail (transient error) | usage (usage-limit error) | hang (sleeps with a child process) |
bad_json | flaky (bad_json on the first attempt, ok on the second).
Global context: lets tests exercise codex_runner/pipeline end to end (streaming, retries, timeouts,
process-tree kill) for free; settings.codex_cmd points here instead of the real codex.exe.
"""

import json  # emit JSONL events and build the fake answer
import re  # find the MODE=<name> marker
import subprocess  # spawn a grandchild process in "hang" mode (to test process-tree kill)
import sys  # argv, stdin/stdout/stderr
import time  # sleep in "hang" mode
from pathlib import Path  # agent folder and output files


def arg(flag: str) -> str:
    """Value following a CLI flag, e.g. arg('--cd')."""
    return sys.argv[sys.argv.index(flag) + 1]


def emit(event: dict) -> None:
    """Print one JSONL event and flush so the runner sees it immediately."""
    print(json.dumps(event, ensure_ascii=False), flush=True)


def answer_from_schema(schema_path: str) -> str:
    """A valid answer for the given --output-schema: one item using the first enum value of each dimension."""
    props = json.loads(Path(schema_path).read_text(encoding="utf-8"))["properties"]["items"]["items"]["properties"]
    item = {k: (v["enum"][0] if "enum" in v else f"fake {k}") for k, v in props.items()}
    item.update(url="https://example.org/fake", published="unknown")
    return json.dumps({"items": [item], "coverage_notes": "fake notes"})


def main() -> int:
    """Run one fake agent turn; return the process exit code."""
    sys.stdout.reconfigure(encoding="utf-8")  # match the runner's UTF-8 decoding
    prompt = sys.stdin.buffer.read().decode("utf-8")  # raw bytes: lets tests check byte-identical delivery
    cwd, out = Path(arg("--cd")), Path(arg("--output-last-message"))
    (cwd / "received_prompt.txt").write_bytes(prompt.encode("utf-8"))
    found = re.search(r"MODE=(\w+)", prompt)  # anywhere in the prompt, e.g. inside a topic name
    mode = found.group(1) if found else "ok"
    if mode == "flaky":  # first call fails validation, second succeeds
        marker = cwd / "flaky_marker"
        mode = "ok" if marker.exists() else "bad_json"
        marker.touch()
    emit({"type": "thread.started", "thread_id": "fake"})
    emit({"type": "turn.started"})
    if mode == "hang":  # child + long sleep: the runner's timeout must kill both
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        (cwd / "child_pid.txt").write_text(str(child.pid), encoding="utf-8")
        time.sleep(120)
        return 0
    if mode in ("fail", "usage"):
        msg = "You've hit your usage limit." if mode == "usage" else "stream disconnected before completion"
        emit({"type": "error", "message": msg})
        emit({"type": "turn.failed", "error": {"message": msg}})
        print(f"fatal: {msg}", file=sys.stderr, flush=True)
        return 1
    emit({"type": "item.completed", "item": {"id": "item_0", "type": "web_search", "query": "fake query",
                                             "action": {"type": "search", "query": "fake query"}}})
    text = "not json" if mode == "bad_json" else answer_from_schema(arg("--output-schema"))
    emit({"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": text}})
    emit({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})
    out.write_text(text, encoding="utf-8")  # what -o/--output-last-message produces
    return 0


if __name__ == "__main__":
    sys.exit(main())
