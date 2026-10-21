# Architecture

How the code is organised and what a run leaves on disk. Usage is in [../README.md](../README.md); Codex CLI
specifics and live-run measurements are in [codex-exec-notes.md](codex-exec-notes.md).

## Modules (`src/agentic_news/`)

| Module | Responsibility | I/O |
|---|---|---|
| `settings.py` | `.env` + environment overrides → frozen `Settings` (uses `dotenv_values`, never writes `os.environ`) | reads `.env` |
| `logging_setup.py` | `logs/run_<run_id>.log` + stdout, millisecond timestamps, untruncated | log file |
| `catalog.py` | 24 default topics, 4 dimensions (stable ids, labels, definitions), `build_jobs(rows)`, `interval_ranges(today)` | none |
| `prompts.py` | `build_prompt(job, today, ...)`: topic, date ranges, selected option definitions, search plan, rules, output contract | none |
| `schema.py` | `build_output_schema(job)` (strict structured-output subset), `parse_final(...)` (validate, drop non-http(s) and duplicate links, re-file mis-dated items, `in_interval`, `url_seen`) | none |
| `events.py` | render Codex JSONL events as full log text, counters, searched URLs, fatal-error check | none |
| `store.py` | atomic JSON (Windows `PermissionError` retry), results JSON/CSV, `list_runs`, thread-safe `StatusBoard` | `runs/`, `data/` |
| `codex_runner.py` | build the `codex exec` argv, run one process per topic, stream events, timeout + process-tree kill, retries, thread pool | agent folders |
| `pipeline.py` | **the wrapper**: `load_selection → build_jobs → prepare_agent_dirs → run_agents → collect_results → save_results` | via `store` |
| `cli.py` | `agentic-news run [--run-id] [--selection]`; writes a failed status if the run crashes | — |
| `launcher.py` | dashboard helpers: start the CLI in the background, `is_active`, `stop_run` | `runs/` |
| `../../app.py` | Streamlit UI (selection table, status, results); never runs agents itself | reads run files |

## Process model

```
streamlit (app.py)
└─ python -m agentic_news.cli run --run-id R      (launcher.launch_run, CREATE_NEW_PROCESS_GROUP on Windows)
   └─ ThreadPoolExecutor(MAX_PARALLEL_AGENTS)
      ├─ codex exec ... -   (topic 1, prompt on stdin, JSONL on stdout)
      ├─ codex exec ... -   (topic 2)
      └─ ...
```

- The run process shares the Streamlit terminal, so the live log is visible there; it survives browser reloads
  and Ctrl+C in that terminal, but closing the terminal window ends it. For unattended runs use the CLI directly.
- Each worker thread blocks on its own subprocess and reads stdout line by line; a second thread drains stderr.
- Timeout: a `threading.Timer` kills the Codex process **and its children** (`psutil`), so shells started by
  the agent don't outlive it. Timeouts and usage-limit/auth errors are not retried; other failures are retried
  `AGENT_MAX_RETRIES` times.
- `StatusBoard` is the only writer of `status.json`: forced writes on state changes, throttled (≤1/s) writes
  for event counters. The dashboard polls it every 2 s with an `st.fragment(run_every=2)`.
- **Stop** in the dashboard kills the run's process tree (all agents) and marks the run `stopped`.

## Run folder

```
runs/<run_id>/
  selection.json            snapshot of the table rows this run used
  status.json               live run + per-agent status (below)
  results.json, results.csv all rows, written when the run ends
  <topic-slug>/
    prompt.md               full prompt sent on stdin
    schema.json             --output-schema for this topic (enums = selected options)
    events_attempt<N>.jsonl raw Codex JSONL, one file per attempt
    final.json              last agent message (-o / --output-last-message)
    items.json              parsed rows (lets the dashboard show results before the run ends)
logs/run_<run_id>.log       everything above, rendered, plus launch commands and stderr
data/selection.json         the dashboard table, saved on every edit (default input for headless runs)
```

`status.json`: `run_id, state (starting|running|done|failed|stopped), pid, started, ended, error?` and
`agents.<slug>: topic, cells, state (queued|running|done|failed|timeout), attempt, pid, started, ended, items,
searches, commands, input_tokens, output_tokens, last_event, error, coverage_notes`. The launcher writes a
`starting` status before the run process exists; the run's StatusBoard then replaces it.

## Result columns

| Column | Source | Meaning |
|---|---|---|
| `topic` | Python | the table row's topic |
| `interval`, `type`, `source`, `variant` | model (enum-constrained), `interval` possibly re-filed by Python | the cell the item belongs to |
| `title`, `url`, `published`, `creator`, `summary`, `why_notable` | model | item details; `published` is `YYYY-MM-DD`, `YYYY-MM`, `YYYY` or `unknown` |
| `in_interval` | Python | publication date overlaps the interval's range (`None` when unknown) |
| `url_seen` | Python | the link appeared in this agent's `web_search` events (opened page or result list) |
| `run_id` | Python | run that produced the row |

Re-filing: if an item's date falls outside its interval but inside another *selected* interval, it moves to
the narrowest such interval (selected intervals are ordered day → century).
