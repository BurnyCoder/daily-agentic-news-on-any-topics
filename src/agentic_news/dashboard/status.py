"""Dashboard section 4: live status of the latest run, refreshed every 2 s.

Local: a fragment with run_every (https://docs.streamlit.io/develop/api-reference/execution-flow/st.fragment)
re-reads runs/<latest>/status.json without rerunning the page; when the run finishes it reruns the whole app
so the Get News button and results refresh.
Global context: status.json is written only by the run's StatusBoard (store.py) in the background CLI process.
"""

import pandas as pd  # status table
import streamlit as st  # UI

from agentic_news.launcher import is_active, stop_run  # run control
from agentic_news.settings import Settings  # runs_dir
from agentic_news.store import list_runs, read_json  # run files


def latest_active(settings: Settings) -> bool:
    """Is the newest run still going?"""
    runs = list_runs(settings.runs_dir)
    return bool(runs) and is_active(read_json(settings.runs_dir / runs[0] / "status.json"))


def render_status(settings: Settings) -> None:
    """Section UI as an auto-refreshing fragment."""
    st.fragment(run_every=2)(_status_body)(settings)


def _status_body(settings: Settings) -> None:
    runs = list_runs(settings.runs_dir)
    if not runs:
        st.caption("No runs yet.")
        return
    run_dir = settings.runs_dir / runs[0]
    status = read_json(run_dir / "status.json", default={}) or {}
    active = is_active(status)
    state = "interrupted" if not active and status.get("state") in ("starting", "running") else status.get("state")
    agents = status.get("agents", {}).values()
    done = sum(a["state"] in ("done", "failed", "timeout") for a in agents)
    st.markdown(f"Run **{runs[0]}**: **{state}** · {done}/{len(agents)} agents finished · started "
                f"{status.get('started')} · log `logs/run_{runs[0]}.log`")
    if agents:
        st.dataframe(pd.DataFrame([{"agent": a.get("label", a.get("topic")), "state": a["state"],
                                    "attempt": a["attempt"], "cells": a["cells"], "searches": a["searches"],
                                    "items": a["items"], "off-grid dropped": a.get("dropped", 0),
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
