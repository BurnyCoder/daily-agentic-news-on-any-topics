"""Streamlit dashboard: pick topics and forms in a table, click Get News, watch the agents live, browse results.

Local: three sections, top to bottom —
1. the selection table (st.data_editor with MultiselectColumn, https://docs.streamlit.io/develop/api-reference/data/st.data_editor),
   saved to data/selection.json on every edit, plus bulk-edit buttons and the Get News button;
2. live agent status of the latest run (st.fragment with run_every polls status.json,
   https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment);
3. the filterable results table (st.dataframe + LinkColumn), coverage pivot and CSV download.
Global context: the dashboard never runs agents itself; launcher.launch_run starts the background CLI
(cli -> pipeline -> codex_runner) and this page only reads the files that run writes.
Start with: `uv run streamlit run app.py`.
"""

import pandas as pd  # tables
import streamlit as st  # UI

from agentic_news.catalog import DIMENSIONS, ITEM_FIELD, build_jobs, default_rows  # options + jobs
from agentic_news.launcher import is_active, launch_run, stop_run  # background run control
from agentic_news.settings import load_settings  # .env
from agentic_news.store import RESULT_COLUMNS, list_runs, load_results, read_json, write_json  # files

SETTINGS = load_settings()
SELECTION_PATH = SETTINGS.data_dir / "selection.json"  # survives restarts; also used by headless runs
LABELS = {dim: {oid: opt.label for oid, opt in opts.items()} for dim, opts in DIMENSIONS.items()}


def _as_list(value: object) -> list:
    """Multiselect cell -> list (new editor rows hold None/NaN)."""
    return list(value) if hasattr(value, "__iter__") and not isinstance(value, str) else []


def clean_rows(df: pd.DataFrame) -> list[dict]:
    """Editor dataframe -> JSON-safe selection rows."""
    return [{"run": r["run"] is True, "topic": r["topic"] if isinstance(r["topic"], str) else "",
             **{dim: _as_list(r[dim]) for dim in DIMENSIONS}} for r in df.to_dict("records")]


def replace_rows(rows: list[dict]) -> None:
    """Swap the editor's base data (bulk edits) — a new editor key discards stale cell edits."""
    write_json(SELECTION_PATH, rows)
    st.session_state.base_rows = rows
    st.session_state.editor_version += 1
    st.rerun()


def render_selection() -> list[dict]:
    """Editable topic x forms table; returns the current rows."""
    if "base_rows" not in st.session_state:  # load once: feeding edits back as input would reset the editor
        st.session_state.base_rows = read_json(SELECTION_PATH) or default_rows()
        st.session_state.editor_version = 0
    config = {"run": st.column_config.CheckboxColumn("Run", default=False, width="small"),
              "topic": st.column_config.TextColumn("Topic", required=True, width="medium"),
              **{dim: st.column_config.MultiselectColumn(dim.title(), options=list(opts), default=list(opts),
                                                         format_func=LABELS[dim].get)
                 for dim, opts in DIMENSIONS.items()}}
    edited = st.data_editor(pd.DataFrame(st.session_state.base_rows, columns=["run", "topic", *DIMENSIONS]),
                            column_config=config, num_rows="dynamic", hide_index=True,
                            key=f"editor_{st.session_state.editor_version}")
    rows = clean_rows(edited)
    if rows != read_json(SELECTION_PATH):
        write_json(SELECTION_PATH, rows)  # persist every edit
    with st.expander("Bulk edit"):
        picks = {dim: col.multiselect(dim.title(), list(opts), default=list(opts), format_func=LABELS[dim].get,
                                      key=f"bulk_{dim}") for col, (dim, opts) in zip(st.columns(4), DIMENSIONS.items())}
        apply, check, uncheck, reset = st.columns(4)
        if apply.button("Apply forms to checked rows"):
            replace_rows([{**r, **picks} if r["run"] else r for r in rows])
        if check.button("Check all"):
            replace_rows([{**r, "run": True} for r in rows])
        if uncheck.button("Uncheck all"):
            replace_rows([{**r, "run": False} for r in rows])
        if reset.button("Reset to default topics"):
            replace_rows(default_rows())
    return rows


def render_launch(rows: list[dict], active: bool) -> None:
    """Run preview and the Get News button."""
    jobs = build_jobs(rows)
    cells = [job.cells for job in jobs]
    st.markdown(f"**{len(jobs)}** topic agent(s) · **{sum(cells)}** cells · up to {SETTINGS.items_per_cell} "
                f"item(s) per cell, max {SETTINGS.max_items_per_agent} per agent · `{SETTINGS.codex_model}` · "
                f"{SETTINGS.max_parallel_agents} agents in parallel")
    if cells and max(cells) * SETTINGS.items_per_cell > SETTINGS.max_items_per_agent:
        st.warning(f"Some topics have up to {max(cells)} cells: each agent returns at most "
                   f"{SETTINGS.max_items_per_agent} items, so many cells will stay empty. Narrow the forms for fuller coverage.")
    if st.button("Get News", type="primary", disabled=active or not jobs, key="get_news"):
        launch_run(rows, SETTINGS)
        st.rerun()


@st.fragment(run_every=2)
def render_status() -> None:
    """Live status of the latest run, refreshed every 2 s without rerunning the whole page."""
    runs = list_runs(SETTINGS.runs_dir)
    if not runs:
        st.caption("No runs yet.")
        return
    run_dir = SETTINGS.runs_dir / runs[0]
    status = read_json(run_dir / "status.json", default={}) or {}
    active = is_active(status)
    state = "interrupted" if not active and status.get("state") in ("starting", "running") else status.get("state")
    agents = status.get("agents", {}).values()
    done = sum(a["state"] in ("done", "failed", "timeout") for a in agents)
    st.markdown(f"Run **{runs[0]}**: **{state}** · {done}/{len(agents)} agents finished · started "
                f"{status.get('started')} · log `logs/run_{runs[0]}.log`")
    if agents:
        st.dataframe(pd.DataFrame([{"topic": a["topic"], "state": a["state"], "attempt": a["attempt"],
                                    "cells": a["cells"], "searches": a["searches"], "items": a["items"],
                                    "tokens in": a["input_tokens"], "tokens out": a["output_tokens"],
                                    "last event / error": a.get("error") or a["last_event"]} for a in agents]),
                     hide_index=True)
    if status.get("error"):
        st.error(status["error"])
    if active and st.button("Stop run"):
        stop_run(run_dir)
        st.rerun()
    if st.session_state.get("was_active") and not active:
        st.session_state.was_active = False
        st.rerun()  # run finished: refresh the whole page (button state, results)
    st.session_state.was_active = active


def render_results() -> None:
    """Filterable results table of a chosen run."""
    runs = list_runs(SETTINGS.runs_dir)
    if not runs:
        return
    run_id = st.selectbox("Run", runs)
    df = pd.DataFrame(load_results(SETTINGS.runs_dir / run_id), columns=RESULT_COLUMNS)
    for dim, field in ITEM_FIELD.items():
        df[field] = df[field].map(LABELS[dim]).fillna(df[field])  # ids -> readable labels
    for flag in ("in_interval", "url_seen"):
        df[flag] = df[flag].map({True: "yes", False: "no"}).fillna("unknown")  # tri-state for display
    filters = st.columns(6)
    for col, field in zip(filters, ["topic", *ITEM_FIELD.values()]):
        if chosen := col.multiselect(field.title(), sorted(df[field].dropna().unique())):
            df = df[df[field].isin(chosen)]
    if query := filters[5].text_input("Search text"):
        text = df[["title", "creator", "summary", "why_notable"]].astype(str).agg(" ".join, axis=1)
        df = df[text.str.contains(query, case=False, regex=False)]
    st.caption(f"{len(df)} item(s)")
    st.dataframe(df.drop(columns=["run_id"]), hide_index=True,
                 column_config={"url": st.column_config.LinkColumn("Link", display_text="open"),
                                "in_interval": st.column_config.TextColumn("Date in range"),
                                "url_seen": st.column_config.TextColumn(
                                    "Link from search", help="The link appeared in the agent's web search results")})
    st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"), file_name=f"news_{run_id}.csv")
    with st.expander("Coverage: items per topic x interval"):
        st.dataframe(pd.crosstab(df["topic"], df["interval"]) if len(df) else df)
    with st.expander("Agents' coverage notes"):
        for agent in (read_json(SETTINGS.runs_dir / run_id / "status.json", default={}) or {}).get("agents", {}).values():
            st.markdown(f"**{agent['topic']}** ({agent['state']}): {agent.get('coverage_notes') or agent.get('error') or '-'}")


st.set_page_config(page_title="Agentic News", layout="wide")
st.title("Agentic News")
st.caption(f"Check topics, choose their forms, click Get News: one Codex agent ({SETTINGS.codex_model}, live web "
           "search, no sandbox) per checked topic.")
_runs = list_runs(SETTINGS.runs_dir)
_active = bool(_runs) and is_active(read_json(SETTINGS.runs_dir / _runs[0] / "status.json"))
st.header("1. Topics and forms")
render_launch(render_selection(), _active)
st.header("2. Agents")
render_status()
st.header("3. Results")
render_results()
