# Codex CLI notes and live-run findings

Everything here was checked against **codex-cli 0.163.0** on Windows 11 (October 2026). `uv run pytest -m cli`
re-checks the flag, feature and model names against whatever Codex version is installed.

## The command each topic agent runs

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
| `--disable ...` | skips plugin/app catalogs and sub-agent fan-out per agent; feature names are listed by `codex features list` |
| `--output-schema` | strict JSON answer; Codex applies it to **every** agent message, not just the last ([openai/codex#19816](https://github.com/openai/codex/issues/19816)), hence the prompt's "no progress messages" rule |
| `-o` + trailing `-` | final answer in a file; prompt read from stdin (avoids Windows quoting and command-line length limits) |

All `-c` keys were also accepted with `--strict-config` in a probe run.

## Event stream (real sample)

The first lines of [tests/fixtures/events_sample.jsonl](../tests/fixtures/events_sample.jsonl) are an unedited
gpt-6-luna stream:

- `thread.started {thread_id}` → `turn.started`
- `item.started` / `item.completed` with `item.type = "web_search"`:
  - `query`
  - `action` = `{type: "search", queries:[...]}` or `{type: "open_page", url}`
  - `results` = `[{title, url, domain, snippet}]`
- `item.completed` with `item.type = "agent_message"` and `text` (the JSON answer)
- `turn.completed` with `usage`: `input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`,
  `output_tokens`, `reasoning_output_tokens`

One web_search call usually bundles several queries. With `model_reasoning_summary="auto"`, `reasoning`
items are short headings such as `**Preparing 30 search queries**`. There were 0–4 per agent at `medium` and
12 at `high`; they are logged like every other event.

## Live runs

Setup for every run:
- each topic had the full form: 6 intervals × 5 types × 4 sources × 2 variants = 240 cells
- `ITEMS_PER_CELL=2`, `MAX_ITEMS_PER_AGENT=60`
- data comes from `runs/<id>/status.json`, `events_attempt1.jsonl` and `items.json`

Each configuration ran once, so differences between rows are indicative only; they are not statistically
tested.

**Pure math**

| Run | Change vs previous | Effort | Calls / queries | Items | Links from search | Dated in interval |
|---|---|---|---|---|---|---|
| 1 `20261022-012502` | baseline prompt | medium | 5 / 20 | 9 | 9 | 6 |
| 2 `20261022-012857` | + search plan, re-filing, `url_seen` | medium | 4 / 16 | 16 | 13 | 15 |
| 3 `effort-high-puremath` | same prompt as run 2 | **high** | 12 / 42 | 4 | 4 | 4 |
| 4 `relaxed-puremath` | relaxed evidence rules | medium | 4 / 68 | 17 | 12 | 17 |
| 5 `verify-three` | + "open unknown URLs first" | medium | 10 / 38 | 13 | 8 | 11 |

**Mechanistic interpretability**

| Run | Calls / queries | Items | Links from search | Dated in interval |
|---|---|---|---|---|
| 1 | 5 / 20 | 23 | 16 | 16 |
| 2 | 6 / 23 | 18 | 16 | 18 |
| 5 | 17 / 66 | 19 | 9 | 18 |

**AI governance** (run 5 only): 2 calls / 8 queries, 24 items, 18 links from search, 24 dated in interval.

**Durations:** 41–79 s per run; agents ran in parallel. **Input tokens:** 76k–749k per agent, most of them
cached. Run 1's links-from-search counts were computed afterwards from its event files, because the flag did
not exist yet.

### What we learned and what changed

1. **Thin coverage.** One agent with 240 cells returned 9–23 items after about 5 search calls. The model ignored
   "at least N searches" (run 2).
2. **Higher effort made it stricter, not broader** (run 3).
   - It made 3× the search calls but returned 4 items.
   - Its coverage notes said it rejected candidates whose virality or date "could not be verified".
   - So the default stays `medium`.
3. **Relaxing the evidence rule raised recall but let a placeholder through** (run 4).
   - The new rule: fill every real cell, and influence counts as notability for the 10/100-year intervals.
   - Recall rose (17 items, 68 queries).
   - But one link was the placeholder `https://www.youtube.com/watch?v=REPLACE`. The `url_seen` flag marked it,
     because it never appeared in a search result.
4. **The model does not open pages it remembers** (run 5).
   - Even when told to open unknown URLs first, it made 0 `open_page` calls.
   - Links not from search are mostly real classics recalled from training: *As We May Think* (1945), the Moral
     Machine paper (Nature 2018), *Toy Models of Superposition*.
   - A few are doubtful: an X post ID, and a YouTube *search page* instead of a video.
   - So these links stay in the table, flagged. The dashboard has an "Only links from search results" filter.
5. **Interval mistakes are common** (run 1: 16/23 and 6/9 dated inside their interval).
   - Python now moves a mis-dated item to the narrowest selected interval that contains its date (runs 2–5).
   - Items that fit no selected interval stay flagged. Example: the model files Riemann's 1859 paper under
     "last 100 years".

Open levers, not implemented:
- split a topic into several agents (for example one per interval);
- resume the Codex session to fill empty cells (`codex exec resume`);
- a stronger model (`CODEX_MODEL`).
