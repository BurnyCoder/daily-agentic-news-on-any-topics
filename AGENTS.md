# AGENTS.md — working on this repository

Guide for coding agents (Codex, Claude Code, ...) changing this repo. What the project does and how to use it is
in [README.md](README.md); module internals are in [docs/architecture.md](docs/architecture.md); Codex CLI details and
live-run findings are in [docs/codex-exec-notes.md](docs/codex-exec-notes.md).

## Commands

```bash
uv sync                                   # install deps into .venv (Python 3.14)
uv run pytest                             # unit + end-to-end tests on a fake codex (no tokens)
uv run pytest -m cli                      # check flags/features/model against the installed codex CLI
uv run pytest -m live -s                  # one real gpt-6-luna agent (spends tokens)
uv run streamlit run app.py               # dashboard on http://localhost:8501
uv run agentic-news run                   # headless run of the saved selection
```

## Rules for changes

- `src/agentic_news/pipeline.py` is the only orchestration wrapper; add new work as a named phase there and
  put the logic in its own module.
- Keep `catalog.py`, `prompts.py`, `schema.py`, `events.py` free of I/O; all file access goes through `store.py`.
- `app.py` is UI only: it reads run files and calls `launcher.py`; it never runs agents itself.
- Every prompt, Codex event and final answer must keep reaching the run log untruncated (`logging_setup.py`);
  only the UI may shorten text.
- The output schema must stay valid for OpenAI strict structured outputs (object root, every property
  required, `additionalProperties: false`, no length/format keywords); `tests/test_schema.py` enforces it.
- Changing a Codex flag, feature name or model? Run `uv run pytest -m cli` and `uv run pytest -m live -s`.
- Tests first: the fake Codex (`tests/fixtures/fake_codex.py`, behaviour chosen by `MODE=<name>` in the prompt)
  covers process handling without tokens.
- Never commit `.env`, `logs/`, `runs/` or `data/` (logs contain full prompts and fetched web content).
- Every file starts with a docstring giving local purpose and global context; cite docs/issues for non-obvious
  library or CLI behaviour.
