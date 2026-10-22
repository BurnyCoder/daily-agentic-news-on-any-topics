# Codex CLI notes and live-run findings

Everything here was checked against **codex-cli 0.163.0** on Windows 11 (October 2026). `uv run pytest -m cli`
re-checks the flag, feature and model names against whatever Codex version is installed. Run numbers come from
the local, git-ignored `runs/<id>/` and `logs/` folders, except the two live tests (see below).

## The command each agent runs

```
codex exec --json --color never --model gpt-6-luna
  -c model_reasoning_effort="medium" -c model_reasoning_summary="auto" -c web_search="live"
  -c project_doc_max_bytes=0
  --dangerously-bypass-approvals-and-sandbox --ephemeral --skip-git-repo-check --ignore-user-config
  --disable plugins --disable remote_plugin --disable apps --disable plugin_sharing --disable tool_suggest --disable multi_agent
  --cd runs/<run_id>/<slug> --output-schema runs/<run_id>/<slug>/schema.json
  --output-last-message runs/<run_id>/<slug>/final.json -
```

| Part | Why |
|---|---|
| `--json` | JSONL event stream on stdout, logged live ([non-interactive mode docs](https://learn.chatgpt.com/docs/non-interactive-mode)) |
| `--model gpt-6-luna` | slug from `codex debug models` ("GPT-6-Luna", "Fast and affordable model for easier tasks", 272k context) |
| `-c web_search="live"` | `codex exec` has no `--search` flag; `"live"` is documented as the same as `--search` ([config basics](https://learn.chatgpt.com/docs/config-file/config-basic.md)) |
| `-c project_doc_max_bytes=0` | agent folders live inside this git repo; without it the repo's `AGENTS.md` is injected into every news agent's prompt (verified with `codex debug prompt-input` run from an agent folder: present by default, absent with the flag) |
| `--dangerously-bypass-approvals-and-sandbox` | the user asked for agents with no sandbox and no approval prompts |
| `--ephemeral` | no session files; the raw events are already saved per attempt |
| `--skip-git-repo-check` | agent folders are not repositories |
| `--ignore-user-config` | does not load `$CODEX_HOME/config.toml` (e.g. personal MCP servers); "auth still uses `CODEX_HOME`" per `codex exec --help` (`CODEX_IGNORE_USER_CONFIG=false` to turn off) |
| `--disable ...` | turns off the plugin, app, tool-suggestion and multi-agent (sub-agent) features for news agents; each flag equals `-c features.<name>=false` (`codex exec --help`), and the names are listed by `codex features list` |
| `--output-schema` | strict JSON answer; Codex applies it to **every** agent message, not just the last ([openai/codex#19816](https://github.com/openai/codex/issues/19816)), hence the prompt's "no progress messages" rule |
| `-o` + trailing `-` | final answer in a file; prompt read from stdin (avoids Windows quoting and command-line length limits) |

All `-c` keys above pass `--strict-config`, which does check `-c` overrides: a made-up key fails with
"unknown configuration field `bogus_key_xyz` in -c/--config override".

## Event stream (real sample)

The first 6 lines of [tests/fixtures/events_sample.jsonl](../tests/fixtures/events_sample.jsonl) are an unedited
gpt-6-luna stream; the remaining lines are synthetic edge cases. The docs name the events in prose; the exact
field names are in [codex-rs/exec/src/exec_events.rs](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/exec/src/exec_events.rs).
Shapes seen in the fixture and in `runs/*/*/events_attempt*.jsonl`:

- `thread.started {thread_id}` → `turn.started`
- `item.started` / `item.completed` with `item.type = "web_search"`:
  - `query`
  - `action` = `{type: "search", queries:[...]}`, `{type: "open_page", url}` or `{type: "other"}`
  - `results` = `[{type, title, url, domain, snippet, ref_id}]`
- `item.completed` with `item.type = "agent_message"` and `text` (the JSON answer)
- `turn.completed` with `usage`: `input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`,
  `output_tokens`, `reasoning_output_tokens`

One web_search call usually bundles several queries. gpt-6-luna's catalog entry has
`default_reasoning_summary: "none"` (`codex debug models`), and Codex drops reasoning items with empty text
([event_processor_with_jsonl_output.rs](https://github.com/openai/codex/blob/rust-v0.163.0/codex-rs/exec/src/event_processor_with_jsonl_output.rs)),
hence `model_reasoning_summary="auto"`. The `reasoning` items are then short headings such as
`**Preparing 30 search queries**`. There were 0–6 per agent at `medium` and 12 in the one `high` run; they are
logged like every other event.

## Live runs, first version: one agent per topic

Setup for every run:
- each topic had the full form: 6 intervals × 5 types × 4 sources × 2 variants = 240 cells
- `ITEMS_PER_CELL=2`, `MAX_ITEMS_PER_AGENT=60`
- data comes from `runs/<id>/status.json`, `events_attempt1.jsonl` and `items.json`

Each configuration ran once, except run 5's prompt on Pure math, which ran twice (5 and 5b: 13 vs 15 items,
8 vs 11 links from search). That replicate is the only measure of run-to-run noise, and it is as large as most
differences between rows, so the differences are indicative only; none is statistically tested.

**Pure math**

| Run | Change vs previous | Effort | Calls / queries | Items | Links from search | Dated in interval |
|---|---|---|---|---|---|---|
| 1 `20261022-012502` | baseline prompt | medium | 5 / 20 | 9 | 9 | 6 |
| 2 `20261022-012857` | + search plan, re-filing, `url_seen` | medium | 4 / 16 | 16 | 13 | 15 |
| 3 `effort-high-puremath` | same prompt as run 2 | **high** | 12 / 40 | 4 | 4 | 4 |
| 4 `relaxed-puremath` | relaxed evidence rules | medium | 4 / 68 | 17 | 12 | 17 |
| 5 `verify-three` | + "open unknown URLs first" | medium | 10 / 38 | 13 | 8 | 11 |
| 5b `20261022-014742` | same prompt as run 5 (repeat) | medium | 7 / 28 | 15 | 11 | 15 |

**Mechanistic interpretability**

| Run | Calls / queries | Items | Links from search | Dated in interval |
|---|---|---|---|---|
| 1 | 5 / 20 | 23 | 16 | 16 |
| 2 | 6 / 23 | 18 | 16 | 18 |
| 5 | 17 / 66 | 19 | 9 | 18 |

**AI governance** (run 5 only): 2 calls / 8 queries, 24 items, 18 links from search, 24 dated in interval.

Calls count every completed `web_search` item; queries count the search queries inside them (run 3's 12 calls
include 2 of type `other` with no query). **Durations:** 41–79 s per run; agents ran in parallel. **Input
tokens:** 76k–749k per agent (run 3: 749k, of which 657k cached). Run 1's links-from-search counts were computed
afterwards from its event files, because the flag did not exist yet.

### What we learned and what changed

1. **Thin coverage.** In runs 1–2, one agent with 240 cells returned 9–23 items after 4–6 search calls. Run 2's
   prompt asked for "at least 30 searches in total"; its agents ran 16 and 23 queries.
2. **Higher effort made it stricter, not broader** (run 3, a single run).
   - It made 3× the search calls of run 2 (12 vs 4) but returned 4 items instead of 16.
   - Its coverage notes said candidates were left out when their dates or virality "could not be verified".
   - So the default stays `medium`.
3. **Relaxing the evidence rule did not clearly change coverage, and let a placeholder through** (run 4).
   - The new rule: fill every real cell, and influence counts as notability for the 10/100-year intervals.
   - Against run 2 (same effort): 16 → 17 items, 13 → 12 links from search, 15 → 17 dated in interval, while
     queries rose 16 → 68. These differences are within the run 5/5b noise.
   - One link was the placeholder `https://www.youtube.com/watch?v=REPLACE`. The `url_seen` flag marked it,
     because it never appeared in a search result.
4. **The model does not open pages it remembers** (runs 5 and 5b).
   - Even when told to open unknown URLs first, it made 0 `open_page` calls.
   - No run executed a shell command, so links not from search were recalled from training or copied from
     search-result text. Many are well-known older works: *As We May Think* (1945), *Toy Models of
     Superposition*, *In-context Learning and Induction Heads*.
   - Others are doubtful or wrong:
     - two X post links (not checked);
     - a YouTube *search page* instead of a video;
     - a fabricated citation: "The ethics of artificial intelligence: Mapping the debate" (Brent Mittelstadt,
       "Nature Machine Intelligence", 2018) at `nature.com/articles/s41586-018-0633-y`. That DOI does not resolve
       ([doi.org](https://doi.org/api/handles/10.1038/s41586-018-0633-y) and
       [Crossref](https://api.crossref.org/works/10.1038/s41586-018-0633-y) return 404), and the journal's first
       article appeared on 2019-01-07 ([Crossref, ISSN 2522-5839](https://api.crossref.org/journals/2522-5839/works?sort=published&order=asc&rows=1)).
       The model mixed it up with "The ethics of algorithms: Mapping the debate" (Mittelstadt et al., Big Data &
       Society, 2016, [doi:10.1177/2053951716679679](https://doi.org/10.1177/2053951716679679)).
   - So these links stay in the table, flagged. The dashboard has an "Only links from search results" filter.
5. **Interval mistakes are common** (run 1: 16/23 and 6/9 dated inside their interval).
   - Python now moves a mis-dated item to the narrowest selected interval that contains its date (runs 2–5b).
   - Items that fit no selected interval stay flagged. Example: the model files Riemann's 1859 paper under
     "last 100 years".

## Live runs, granular cells and user-chosen batching

Because of finding 1, every combination became its own cell, and batching became a user choice. The default
is now one agent per cell, and any dimensions can be merged into one agent. Live tests stay tiny on purpose
(2 cells), to check the mechanism without spending many credits.

Each configuration ran once:
- **Cell:** AI industry × Articles × Viral news × Pop sci, plus the interval or region shown.
- **Limit:** `ITEMS_PER_CELL=1` in live tests A and B (override in `tests/test_live.py`). The dashboard runs used
  the default 2 (their `config.json` has no override and their `prompt.md` says "up to 2 items"), so their one-cell
  agents returned 2 items each.
- **Data:** from `status.json` and `results.json`. Live tests A and B ran in pytest temp folders that were not
  kept, so their numbers come from the terminal log of `uv run pytest -m live -s`; the dashboard runs are in
  `runs/`.

| Run | Cells | Merge | Agents | Wall time | Searches per agent | Items | Dated in interval / from search | Off-grid dropped |
|---|---|---|---|---|---|---|---|---|
| live test A | last day, last week | none | 2 (parallel) | 13 s | 2, 2 | 2 | 2/2, 2/2 | 0 |
| live test B | last day, last week | interval | 1 | 17 s | 3 | 2 | 2/2, 2/2 | 0 |
| dashboard `20261022-023715` | last week × Region {Europe, USA} (user-added dimension) | none | 2 (parallel) | 18 s | 2, 2 | 4 | 4/4, 4/4 | 0 |

**Input tokens:**
- A one-cell agent used 73–77k input tokens (live test A: 73,095 and 77,430; Region run: 73,390 and 75,427).
- 2-cell agents used 108,447 (live test B, interval merged), 119,269 and 262,613 (run `20261022-030136` below,
  type merged): 1.4–3.5× the mean one-cell agent (74,836), while splitting 2 cells costs 2×.
- With 3 merged agents the saving is not reliable: the 263k agent cost more than two one-cell agents.

**The Region run:**
- The Europe agent searched with the region in its queries ("AI industry Europe October 2026 …").
- It returned European outlets and stories (Euronews on Germany, TechRadar on a Belgian startup).
- The USA agent returned Axios stories.

### What we learned in this round

6. **An error after launch could orphan an unsandboxed agent.**
   - **What happened:** a live test failed early, but the test process only exited after 10 minutes.
   - **Cause:** the runner opened the event file *after* starting Codex. When that raised (see 7), nothing killed
     the process, and the non-daemon timeout timer kept Python alive.
   - **Fix:** open the file first, kill the process tree in a `finally`, and make the timer a daemon.
   - **Guard:** a regression test that fails on the old code and passes on the new.
7. **Windows path length.** A very deep test folder plus an 80-character agent slug pushed paths past 260
   characters. Slugs are now capped at 60 characters, and tests use pytest's short default temp folder.
8. **New dimensions start empty.**
   - Rules first saw the new dimension with no entries, so they selected nothing in it, and later entries never
     got selected (0 cells).
   - Fix: "all stays all". A rule that had every entry of a dimension selected (an empty dimension counts as
     all) also gets entries added later; partial selections stay partial.
9. **Bulk edit overwrote the per-row topic.**
   - Applying a form also replaced each row's Topic with the bulk Topic picker (all topics).
   - Fix: bulk edit now has "Apply these dimensions", which leaves the first dimension (Topic) alone by default.
10. **Results UI:**
    - The run picker kept an old run after a new one finished; it now jumps to the newest run.
    - Grid columns were sorted alphabetically; they now follow each dimension's entry order.
11. **Bulk edit's "Apply these dimensions" kept stale keys.** After a dimension key was renamed (or a dimension
    added), the picker kept its saved value, so the renamed/new dimension was left out. The widget now has no
    fixed key: when the dimensions change it resets to "every dimension except the first".

A merged run checked through the UI: 4 cells (last day/last week × papers/articles) with *Type* merged gave
2 agents of 2 cells each, in 44 s, with 6 items and 0 dropped (run `20261022-030136`). Unlike the 2-cell
tests, not every item was clean: 4/6 links came from search (both AP News articles in the "last day" cell did
not) and 5/6 were dated inside their interval. It also showed the following:
- a renamed dimension key (`variant` → `level`) flows into the prompts and results;
- `results.csv` carries `*_label` columns;
- a paper dated one day before "last day" was flagged out of range rather than moved into the other agent's
  "last week" cell.

Open levers, not implemented:
- resume the Codex session to fill empty cells (`codex exec resume`; it needs session files, so `--ephemeral`
  would have to go);
- a stronger model (`CODEX_MODEL`, or per run in the dashboard).
