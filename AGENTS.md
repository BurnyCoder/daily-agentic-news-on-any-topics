# AGENTS.md — working on this repository

Guide for coding agents (Codex, Claude Code, ...) changing this repo. What the project does and how to use it is
in [README.md](README.md); module internals are in [docs/architecture.md](docs/architecture.md); Codex CLI details and
live-run findings are in [docs/codex-exec-notes.md](docs/codex-exec-notes.md).

## Commands

```bash
uv sync                                   # install deps into .venv (Python 3.14)
uv run pytest                             # unit + end-to-end + UI tests on a fake codex (no tokens)
uv run pytest -m cli                      # check flags/features/model against the installed codex CLI
uv run pytest -m live -s                  # 2 real cells, split vs merged (3 short agent runs, spends tokens)
uv run streamlit run app.py               # dashboard on http://localhost:8501
uv run agentic-news run [--config FILE]   # headless run of data/workspace.json (or FILE)
```

## Rules for changes

- `src/agentic_news/pipeline.py` is the only orchestration wrapper; add new work as a named phase there and
  put the logic in its own module.
- Nothing may assume a fixed set of dimensions: prompts, schema, results and UI are generated from
  `RunConfig.dimensions` (any number, user-editable). Built-in defaults live in `catalog.default_dimensions`.
- Keep `catalog.py`, `config.py`, `prompts.py`, `schema.py`, `events.py` free of I/O. Run and workspace JSON goes
  through `store.py`; the only other file access is `.env` (`settings.py`), the run log (`logging_setup.py`),
  agent folders and `prompt.md` (`pipeline.py`), and event files and `final.json` (`codex_runner.py`).
- `app.py` only calls the `dashboard/` sections; sections read run files and call `launcher.py`, never run agents.
- In the dashboard, data editors use `state.stable_editor` (input snapshotted until `reset_editor`) and widgets
  use keys seeded once; never feed an editor's output back as its input. The one deliberate exception is bulk
  edit's "Apply these dimensions" picker, which has no key so it resets when the dimensions change.
- Every prompt, Codex event and final answer must keep reaching the run log untruncated (`logging_setup.py`);
  only the UI may shorten text.
- The output schema must stay valid for OpenAI strict structured outputs (object root, every property
  required, `additionalProperties: false`) and inside our conservative subset (no length, format, pattern or
  item-count keywords, although strict mode accepts some of them); `tests/test_schema.py` enforces both.
- Changing a Codex flag, feature name or model? Run `uv run pytest -m cli` and `uv run pytest -m live -s`.
  Live tests must stay tiny (a few cells): never test the full cell space.
- Tests first: the fake Codex (`tests/fixtures/fake_codex.py`, behaviour chosen by `MODE=<name>` in the prompt,
  e.g. inside a topic label) covers process handling without tokens; `tests/conftest.py::make_config` builds
  small configs.
- Never commit `.env`, `logs/`, `runs/` or `data/` (logs contain full prompts and fetched web content).
- Every file starts with a docstring giving local purpose and global context; cite docs/issues for non-obvious
  library or CLI behaviour.
