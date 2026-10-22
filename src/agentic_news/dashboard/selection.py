"""Dashboard section 2: choose which cells run, as rules (one multiselect column per dimension).

Local: each checked row selects the Cartesian product of its chosen entries; the selected cells are the union of
all checked rows (catalog.expand_rules). Columns are generated from the current dimensions
(st.column_config.MultiselectColumn, https://docs.streamlit.io/develop/api-reference/data/st.column_config).
Bulk edit applies one set of entries to every checked row; check/uncheck/reset helpers included.
Global context: the selected cells are what the plan section batches into agents.
"""

import pandas as pd  # editor data
import streamlit as st  # UI

from agentic_news.catalog import default_rules, expand_rules  # rules -> cells
from agentic_news.config import RunConfig  # workspace
from agentic_news.dashboard.state import as_list, labels, reset_editor, stable_editor  # editor helpers


def _replace_rules(cfg: RunConfig, rules: list[dict]) -> None:
    """Programmatic rule change: store, re-snapshot the editor, rerun."""
    cfg.rules = rules
    reset_editor("rules")
    st.rerun()


def render_selection(cfg: RunConfig) -> None:
    """Section UI; updates cfg.rules in place."""
    dims, keys = cfg.dimensions, [d.key for d in cfg.dimensions]
    config = {"run": st.column_config.CheckboxColumn("Run", default=False, width="small"),
              **{d.key: st.column_config.MultiselectColumn(d.label, options=d.ids, default=d.ids,
                                                           format_func=labels(d).get) for d in dims}}
    df = stable_editor("rules", lambda: pd.DataFrame(cfg.rules, columns=["run", *keys]),
                       column_config=config, num_rows="dynamic", hide_index=True)
    cfg.rules = [{"run": r["run"] is True, **{k: as_list(r[k]) for k in keys}} for r in df.to_dict("records")]
    with st.expander("Bulk edit"):
        label_of = {d.key: d.label for d in dims}
        apply_to = st.multiselect("Apply these dimensions", keys, default=keys[1:], format_func=label_of.get,
                                  key="bulk_apply_to", help="By default the first dimension (one per row) is kept")
        cols = st.columns(max(len(dims), 1))
        picks = {d.key: col.multiselect(d.label, d.ids, default=d.ids, format_func=labels(d).get, key=f"bulk_{d.key}")
                 for col, d in zip(cols, dims)}
        apply, check, uncheck, reset = st.columns(4)
        if apply.button("Apply entries to checked rows"):
            chosen = {k: picks[k] for k in apply_to}
            _replace_rules(cfg, [{**r, **chosen} if r["run"] else r for r in cfg.rules])
        if check.button("Check all"):
            _replace_rules(cfg, [{**r, "run": True} for r in cfg.rules])
        if uncheck.button("Uncheck all"):
            _replace_rules(cfg, [{**r, "run": False} for r in cfg.rules])
        if reset.button("Reset rows"):
            _replace_rules(cfg, default_rules(dims))
    cells = expand_rules(cfg.rules, dims)
    st.markdown(f"**{len(cells)}** cell(s) selected — each cell is one combination of one entry per dimension.")
