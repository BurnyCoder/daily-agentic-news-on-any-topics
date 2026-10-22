"""Dashboard section 1: edit the dimensions (the rows/columns of the cell space) and their entries.

Local: a table of dimensions (key, label, description, kind, order; a renamed key carries the rules and merge
choices along), a form to add a new dimension, a remove control, and an entries table for the chosen dimension
(add/remove/rename entries, definitions, interval days). Ids and keys are slugified and kept unique
(catalog.unique_name). Any change re-syncs the rules (catalog.sync_rules) and resets the rules editor.
Global context: everything downstream — rules, cells, prompts, output schema, results pivot — is generated
from these dimensions.
"""

from dataclasses import replace  # modified dimension copies

import pandas as pd  # editor data
import streamlit as st  # UI

from agentic_news.catalog import (Dimension, Option, default_dimensions, rename_keys, slugify, sync_rules,
                                  unique_name, validate_dimensions)
from agentic_news.config import RunConfig  # workspace
from agentic_news.dashboard.state import reset_editor, stable_editor, text  # stable editors + cell cleaning

KINDS = ["category", "interval"]


def _apply(cfg: RunConfig, dims: list[Dimension]) -> None:
    """Install new dimensions, fit the rules to them and refresh the dependent editors."""
    if dims != cfg.dimensions:
        cfg.rules = sync_rules(cfg.rules, dims, previous=cfg.dimensions)
        cfg.dimensions = dims
        cfg.merge = [k for k in cfg.merge if k in {d.key for d in dims}]
        reset_editor("rules")


def _key(raw: object) -> str:
    """Dimension key form: lowercase letters, digits and underscores."""
    return slugify(text(raw)).replace("-", "_")


def _dimension_table(cfg: RunConfig) -> tuple[list[Dimension], dict[str, str]]:
    """Edit key/label/description/kind/order of existing dimensions (rows fixed; add/remove below).

    The editor's index holds each row's original key, so a renamed key is traced back to its dimension;
    returns (dimensions in the chosen order, {old key: new key}).
    """
    df = stable_editor("dims", lambda: pd.DataFrame(
        [{"order": n, "key": d.key, "label": d.label, "description": d.description, "kind": d.kind,
          "entries": len(d.options)} for n, d in enumerate(cfg.dimensions, 1)], index=[d.key for d in cfg.dimensions]),
        hide_index=True, num_rows="fixed", disabled=["entries"],
        column_config={"kind": st.column_config.SelectboxColumn("Kind", options=KINDS, required=True),
                       "key": st.column_config.TextColumn("Key", help="Field name used in prompts and results"),
                       "order": st.column_config.NumberColumn("Order", min_value=1, step=1)})
    by_key = {d.key: d for d in cfg.dimensions}
    rows = sorted(((old, r) for old, r in df.to_dict("index").items() if old in by_key), key=lambda kv: kv[1]["order"])
    wanted = {old: _key(r["key"]) or old for old, r in rows}
    renames = {old: unique_name(new, {k for o, k in wanted.items() if o != old}, sep="_")
               for old, new in wanted.items() if new != old}  # a clash with another key gets a suffix
    dims = [replace(by_key[old], key=renames.get(old, old), label=text(r["label"]) or old,
                    description=text(r["description"]), kind=r["kind"]) for old, r in rows]
    return dims, renames


def _entries_table(dim: Dimension) -> Dimension:
    """Edit one dimension's entries; empty ids are derived from labels."""
    columns = ["id", "label", "definition"] + (["days"] if dim.kind == "interval" else [])
    df = stable_editor(f"entries_{dim.key}_{dim.kind}", lambda: pd.DataFrame(
        [{"id": o.id, "label": o.label, "definition": o.definition, "days": o.days} for o in dim.options],
        columns=columns), num_rows="dynamic", hide_index=True,
        column_config={"id": st.column_config.TextColumn("Id", help="Leave empty to derive it from the label"),
                       "days": st.column_config.NumberColumn("Days back", min_value=1, step=1)})
    options, ids = [], set()
    for r in df.to_dict("records"):
        label = text(r["label"]) or text(r["id"])
        if not label:
            continue  # blank new row
        oid = unique_name(slugify(text(r["id"]) or label) or label, ids)  # "Europe" twice -> europe, europe-2
        ids.add(oid)
        days = r.get("days")
        options.append(Option(id=oid, label=label, definition=text(r["definition"]),
                              days=int(days) if dim.kind == "interval" and pd.notna(days) else None))
    return replace(dim, options=tuple(options))


def _restructure(cfg: RunConfig, dims: list[Dimension]) -> None:
    """Add/remove/reset: re-snapshot every dimension editor, apply, and rerun so the tables show the change."""
    for d in [*cfg.dimensions, *dims]:
        reset_editor(f"entries_{d.key}_{d.kind}")
    reset_editor("dims")
    _apply(cfg, dims)
    st.rerun()


def render_dimensions(cfg: RunConfig) -> None:
    """Section UI; updates cfg in place."""
    dims, renames = _dimension_table(cfg)
    if renames:  # carry rules, merge choices and the merge widget over to the new keys
        cfg.rules, cfg.merge = rename_keys(cfg.rules, cfg.merge, renames)
        if "merge" in st.session_state:
            st.session_state["merge"] = [renames.get(k, k) for k in st.session_state["merge"]]
        _restructure(cfg, dims)
    label_of = {d.key: d.label for d in dims}
    add, remove = st.columns(2)
    with add.form("add_dimension", clear_on_submit=True, border=True):
        st.markdown("**Add a dimension**")
        label = st.text_input("Label", placeholder="e.g. Region")
        description = st.text_input("Description for the agent", placeholder="e.g. where the item comes from")
        kind = st.selectbox("Kind", KINDS)
        if st.form_submit_button("Add dimension") and label.strip():
            new = Dimension(key=unique_name(_key(label) or "dimension", {d.key for d in dims}, sep="_"),
                            label=label.strip(), description=description.strip(), kind=kind)
            _restructure(cfg, [*dims, new])  # starts empty: add its entries below
    with remove.container(border=True):
        st.markdown("**Remove a dimension**")
        gone = st.selectbox("Dimension", list(label_of), format_func=label_of.get, key="remove_dim")
        if st.button("Remove dimension", disabled=len(dims) < 2):
            _restructure(cfg, [d for d in dims if d.key != gone])
        if st.button("Reset all dimensions to defaults"):
            _restructure(cfg, default_dimensions())
    st.markdown("**Entries**")
    chosen = st.selectbox("Edit entries of", list(label_of), format_func=label_of.get, key="entries_of")
    _apply(cfg, [_entries_table(d) if d.key == chosen else d for d in dims])
    if errors := validate_dimensions(cfg.dimensions):
        st.error("Fix the dimensions before running: " + "; ".join(errors))
