"""Streamlit dashboard wrapper: calls the dashboard sections in order.

Local: 1. dimensions (edit entries, add dimensions) -> 2. what to run (rules -> granular cells) -> 3. how to run
(batching, parallelism, run settings, prompt rules, Get News) -> 4. live agent status -> 5. results grid + items.
The workspace (RunConfig) lives in session state and is saved to data/workspace.json after every rerun.
Global context: the dashboard never runs agents itself; launcher.launch_run starts the background CLI
(cli -> pipeline -> codex_runner) and the sections only read the files that run writes.
Start with: `uv run streamlit run app.py`.
"""

import streamlit as st  # UI

from agentic_news.dashboard.dimensions import render_dimensions  # section 1
from agentic_news.dashboard.plan import render_plan  # section 3
from agentic_news.dashboard.results import render_results  # section 5
from agentic_news.dashboard.selection import render_selection  # section 2
from agentic_news.dashboard.state import get_config, save_config  # workspace
from agentic_news.dashboard.status import latest_active, render_status  # section 4
from agentic_news.settings import load_settings  # .env

st.set_page_config(page_title="Agentic News", layout="wide")
SETTINGS = load_settings()
cfg = get_config(SETTINGS)
st.title("Agentic News")
st.caption("Every combination of one entry per dimension is a cell. Pick cells, choose which dimensions one agent "
           f"may merge, and click Get News: Codex agents ({SETTINGS.codex_model} by default, live web search, "
           "no sandbox) search them in parallel.")
with st.expander("1. Dimensions and entries", expanded=False):
    render_dimensions(cfg)
st.header("2. What to run")
render_selection(cfg)
st.header("3. How to run")
render_plan(cfg, SETTINGS, latest_active(SETTINGS))
save_config(cfg, SETTINGS)
st.header("4. Agents")
render_status(SETTINGS)
st.header("5. Results")
render_results(SETTINGS)
