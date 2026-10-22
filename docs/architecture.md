# Architecture

How the code is organised and what a run leaves on disk. Usage is in [../README.md](../README.md); Codex CLI
specifics and live-run measurements are in [codex-exec-notes.md](codex-exec-notes.md).

## Concepts

- **Dimension**: `{key, label, description, kind, options}`.
  - `kind="interval"`: options carry `days`, which gives date ranges, re-filing and the date-in-range flag.
  - Any number of dimensions; all user-editable.
- **Option** (entry): `{id, label, definition, days?}`.
- **Cell**: a tuple with one option id per dimension. It is the unit of results.
- **Rule**: a checked row with a list of option ids per dimension. It selects their Cartesian product. The
  selection is the union of the checked rules.
- **Job** (agent batch): `{slug, label, cells}`. `build_jobs` groups the selected cells by the dimensions that
  are *not* merged, then splits groups larger than `max_cells_per_agent`.
- **RunConfig**: dimensions + rules + merge + max cells per agent + per-run setting overrides + prompt rules.

## Modules (`src/agentic_news/`)

| Module | Responsibility | I/O |
|---|---|---|
| `settings.py` | `.env` + environment → frozen `Settings` (`dotenv_values`, never writes `os.environ`); `apply_overrides` for per-run UI values | reads `.env` |
| `catalog.py` | dimensions/options/cells, `default_dimensions`, `validate_dimensions`, `default_rules`, `sync_rules` ("all stays all"), `expand_rules`, `build_jobs`, `interval_ranges` | none |
| `config.py` | `RunConfig`, `default_config`, JSON round-trip | none |
| `prompts.py` | `build_prompt(job, dims, ...)`: dimension blocks with used entries, cells (product or list), search plan, editable rules, output contract | none |
| `schema.py` | `build_output_schema(job, dims)` (one enum per dimension, strict subset); `parse_final` (validate, drop unsafe/duplicate links and off-grid items, re-file dates, flags); `result_columns(dims)` | none |
| `events.py` | render Codex JSONL events as full log text, counters, searched URLs, fatal-error check | none |
| `store.py` | atomic JSON (Windows `PermissionError` retry), results JSON/CSV, `list_runs`, thread-safe `StatusBoard` | `runs/`, `data/` |
| `codex_runner.py` | build the `codex exec` argv, run one process per batch, stream events, timeout + process-tree kill, kill on any error after launch, retries, thread pool | agent folders |
| `pipeline.py` | **the wrapper**: `load_config → expand_rules → build_jobs → prepare_agent_dirs → run_agents → collect_results → save_results` | via `store` |
| `cli.py` | `agentic-news run [--run-id] [--config]`; writes a failed status if the run crashes | — |
| `launcher.py` | start the CLI in the background with a config snapshot, `is_active`, `stop_run` | `runs/` |
| `dashboard/state.py` | workspace in session state, saved to `data/workspace.json`; `stable_editor`/`reset_editor` | `data/` |
| `dashboard/dimensions.py` | edit dimensions (table, add/remove/reset) and their entries | — |
| `dashboard/selection.py` | rules table (one multiselect column per dimension), bulk edit, selected-cell count | — |
| `dashboard/plan.py` | merge/cap/parallelism, run settings, prompt rules, cells → agents preview, confirmation, Get News | — |
| `dashboard/status.py` | live status fragment (every 2 s), stop button | reads `runs/` |
| `dashboard/results.py` | filters, pivot count grid over all selected cells, row/column/cell drill-down, items, CSV | reads `runs/` |
| `../../app.py` | thin wrapper calling the five sections in order | — |

## Process model

```
streamlit (app.py)
└─ python -m agentic_news.cli run --run-id R      (launcher.launch_run, CREATE_NEW_PROCESS_GROUP on Windows)
   └─ ThreadPoolExecutor(max_parallel_agents)
      ├─ codex exec ... -   (batch 1, prompt on stdin, JSONL on stdout)
      ├─ codex exec ... -   (batch 2)
      └─ ...
```

- **Where the run lives:**
  - It shares the Streamlit terminal, so the live log is visible there.
  - It survives browser reloads and Ctrl+C in that terminal; closing the terminal window ends it.
  - For unattended runs use the CLI directly.
- **Reading output:** each worker thread blocks on its own subprocess and reads stdout line by line; a second
  thread drains stderr.
- **Timeout:** a daemon `threading.Timer` kills the Codex process **and its children** (`psutil`), so shells
  started by the agent don't outlive it.
- **Failure handling:**
  - Any exception after launch also kills the process tree, in a `finally`.
  - The raw event file is opened before launch, so a bad path fails before any process exists.
  - Timeouts and usage-limit/auth errors are not retried; other failures are retried `agent_max_retries` times.
- **Status file:** `StatusBoard` is the only writer of `status.json`.
  - Writes are forced on state changes and throttled (≤1/s) for event counters.
  - The dashboard polls it every 2 s.
- **Stop:** the dashboard button kills the run's process tree (all agents) and marks the run `stopped`.

## Files

```
data/workspace.json         the dashboard's RunConfig, saved on every change (default input for headless runs)
runs/<run_id>/
  config.json               snapshot of the RunConfig this run executed (also used for labels in results)
  status.json               live run + per-agent status (below)
  results.json, results.csv all rows, written when the run ends
  <agent-slug>/             one folder per batch (slug ≤ 60 chars, from the batch label)
    prompt.md               full prompt sent on stdin
    schema.json             --output-schema for this batch (enums = the batch's entries)
    events_attempt<N>.jsonl raw Codex JSONL, one file per attempt
    final.json              last agent message (-o / --output-last-message)
    items.json              parsed rows (lets the dashboard show results before the run ends)
logs/run_<run_id>.log       everything above, rendered, plus launch commands, effective settings and stderr
```

`status.json` holds:
- **Run:** `run_id, state (starting|running|done|failed|stopped), pid, started, ended, error?`.
- **`agents.<slug>`:** `label, cells, state (queued|running|done|failed|timeout), attempt, pid, started, ended,
  items, dropped, searches, commands, input_tokens, output_tokens, last_event, error, coverage_notes`.

The launcher writes a `starting` status before the run process exists; the run's StatusBoard then replaces it.

## Result columns

`result_columns(dims)` = one column per dimension (option ids; the UI maps them to labels), then:

| Column | Source | Meaning |
|---|---|---|
| `title`, `url`, `published`, `creator`, `summary`, `why_notable` | model | item details; `published` is `YYYY-MM-DD`, `YYYY-MM`, `YYYY` or `unknown` |
| `in_interval` | Python | publication date overlaps the interval's range (`None` when unknown or no interval dimension) |
| `url_seen` | Python | the link appeared in this agent's `web_search` events (opened page or result list) |
| `agent` | Python | slug of the batch that produced the row |
| `run_id` | Python | run that produced the row |

**Re-filing:** if an item's date falls outside its interval but inside another interval *of the same batch*, it
moves to the narrowest such interval, and only if the resulting cell was selected. Items whose cell is not in the
batch are dropped and counted in the agent's `dropped`.
