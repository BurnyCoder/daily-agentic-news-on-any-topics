"""Dashboard section 5: results of a run — filters, a pivot grid of cells, and the items of selected cells.

Local: the run's own config.json snapshot supplies dimensions and selected cells, so labels and the grid match
what that run searched. The pivot grid counts items per cell over every selected cell (zeros included) with
the dimensions you place on rows and columns; selecting grid rows, columns or cells
(st.dataframe selection, https://docs.streamlit.io/develop/api-reference/data/st.dataframe) lists their items.
Global context: rows come from runs/<id>/results.json (or agents' items.json while the run is going).
"""

import numpy as np  # boolean masks
import pandas as pd  # tables and pivot
import streamlit as st  # UI

from agentic_news.catalog import Dimension, default_dimensions, expand_rules  # dimensions + selected cells
from agentic_news.config import config_from_dict  # run snapshot
from agentic_news.dashboard.state import labels  # id -> label
from agentic_news.schema import result_columns  # column order
from agentic_news.settings import Settings  # runs_dir
from agentic_news.store import list_runs, load_results, read_json  # run files

ALL_ROWS, ALL_COLS = "_rows", "_cols"  # placeholders when no dimension is put on an axis


def _match(df: pd.DataFrame, keys: list[str], values: tuple) -> np.ndarray:
    """Rows of df whose `keys` equal `values` (all rows when keys is empty)."""
    return np.logical_and.reduce([df[k].to_numpy() == v for k, v in zip(keys, values)] or [np.ones(len(df), bool)])


def _ordered(series: pd.Series, dim: Dimension) -> pd.Categorical:
    """Ids -> labels as an ordered categorical in the dimension's entry order (legacy unknown values appended)."""
    values = series.map(labels(dim)).fillna(series)
    order = [o.label for o in dim.options]
    return pd.Categorical(values, categories=order + [v for v in pd.unique(values.dropna()) if v not in order],
                          ordered=True)


def _flat(labels_: pd.Index) -> list[tuple]:
    """Index entries as tuples (MultiIndex or plain)."""
    return [t if isinstance(t, tuple) else (t,) for t in labels_]


def _pivot(df: pd.DataFrame, cells: pd.DataFrame, keys: list[str], rows: list[str], cols: list[str]):
    """Item counts per (row, column) over all selected cells; returns (grid, row tuples, column tuples by name)."""
    counts = (df.groupby(keys, observed=True).size().rename("items").reset_index() if len(df)
              else pd.DataFrame(columns=[*keys, "items"]))
    merged = cells.merge(counts, on=keys, how="left").fillna({"items": 0}).assign(**{ALL_ROWS: "all", ALL_COLS: "items"})
    grid = merged.pivot_table(index=rows or [ALL_ROWS], columns=cols or [ALL_COLS], values="items",
                              aggfunc="sum", fill_value=0, observed=True).astype(int)  # categorical: entry order
    row_tuples, col_tuples = _flat(grid.index), _flat(grid.columns)
    names = [" · ".join(map(str, t)) for t in col_tuples]
    grid.index, grid.columns = [" · ".join(map(str, t)) for t in row_tuples], names
    return grid, row_tuples, dict(zip(names, col_tuples))


def render_results(settings: Settings) -> None:
    """Section UI."""
    runs = list_runs(settings.runs_dir)
    if not runs:
        return
    if st.session_state.get("newest_run") != runs[0]:  # a new run appeared: show it
        st.session_state.newest_run = st.session_state.results_run = runs[0]
    run_id = st.selectbox("Run", runs, key="results_run")
    run_dir = settings.runs_dir / run_id
    snapshot = read_json(run_dir / "config.json")
    cfg = config_from_dict(snapshot) if snapshot else None  # runs from older versions have no snapshot
    dims = cfg.dimensions if cfg else default_dimensions()
    keys = [d.key for d in dims]
    df = pd.DataFrame(load_results(run_dir), columns=result_columns(dims))
    cells = pd.DataFrame(expand_rules(cfg.rules, dims) if cfg else df[keys].drop_duplicates(), columns=keys)
    for d in dims:  # ids -> readable labels in items and cells, kept in entry order
        df[d.key], cells[d.key] = _ordered(df[d.key], d), _ordered(cells[d.key], d)
    for flag in ("in_interval", "url_seen"):
        df[flag] = df[flag].map({True: "yes", False: "no"}).fillna("unknown")

    filters = st.columns(len(dims) + 1)
    for col, d in zip(filters, dims):  # widget keys are per run: each run may have different dimensions
        present = [c for c in cells[d.key].cat.categories if c in set(cells[d.key])]  # entry order
        if chosen := col.multiselect(d.label, present, key=f"filter_{run_id}_{d.key}"):
            df, cells = df[df[d.key].isin(chosen)], cells[cells[d.key].isin(chosen)]
    if query := filters[-1].text_input("Search text", key="filter_text"):
        text = df[["title", "creator", "summary", "why_notable"]].astype(str).agg(" ".join, axis=1)
        df = df[text.str.contains(query, case=False, regex=False)]
    if st.checkbox("Only links that appeared in the agents' search results", key="filter_seen",
                   help="Other links were written from the model's memory: often real classics, but unverified."):
        df = df[df["url_seen"] == "yes"]

    label_of = {d.key: d.label for d in dims}
    interval = next((d.key for d in dims if d.kind == "interval"), keys[-1])
    r, c = st.columns(2)
    rows_key, cols_key = f"grid_rows_{run_id}", f"grid_cols_{run_id}"
    st.session_state.setdefault(rows_key, keys[:1])
    rows = r.multiselect("Grid rows", keys, format_func=label_of.get, key=rows_key)
    st.session_state[cols_key] = [k for k in st.session_state.get(cols_key, [interval]) if k not in rows]
    cols = c.multiselect("Grid columns", [k for k in keys if k not in rows], format_func=label_of.get, key=cols_key)
    grid, row_tuples, col_tuples = _pivot(df, cells, keys, rows, cols)
    st.caption(f"Items per cell over {len(cells)} selected cell(s). Select grid rows, columns or cells to list "
               "their items below.")
    event = st.dataframe(grid, on_select="rerun", selection_mode=["multi-row", "multi-column", "multi-cell"],
                         key=f"pivot_{run_id}")
    sel = event.selection
    if sel.rows or sel.columns or sel.cells:
        mask = np.zeros(len(df), bool)
        for pos in sel.rows:
            mask |= _match(df, rows, row_tuples[pos])
        for name in sel.columns:
            mask |= _match(df, cols, col_tuples[name])
        for pos, name in sel.cells:
            mask |= _match(df, rows, row_tuples[pos]) & _match(df, cols, col_tuples[name])
        df = df[mask]

    st.caption(f"{len(df)} item(s), {int((df['url_seen'] == 'yes').sum())} with links from search results, "
               f"{int((df['in_interval'] == 'yes').sum())} dated inside their interval")
    st.dataframe(df.drop(columns=["run_id"]), hide_index=True,
                 column_config={"url": st.column_config.LinkColumn("Link", display_text="open"),
                                "in_interval": st.column_config.TextColumn("Date in range"),
                                "url_seen": st.column_config.TextColumn(
                                    "Link from search", help="The link appeared in the agent's web search results")})
    st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"), file_name=f"news_{run_id}.csv")
    with st.expander("Agents' coverage notes"):
        for agent in (read_json(run_dir / "status.json", default={}) or {}).get("agents", {}).values():
            st.markdown(f"**{agent.get('label', agent.get('topic'))}** ({agent['state']}): "
                        f"{agent.get('coverage_notes') or agent.get('error') or '-'}")
