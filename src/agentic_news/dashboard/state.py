"""Dashboard state: the workspace RunConfig in session state (saved to data/workspace.json) and stable editors.

Local: `get_config` loads the workspace once per browser session; `save_config` writes it whenever it changed.
`stable_editor` wraps st.data_editor so its *input* stays fixed between reruns — Streamlit keeps edits as
edited_rows/added_rows/deleted_rows relative to the input data, so feeding the edited output back in would
re-apply them (https://docs.streamlit.io/develop/concepts/design/dataframes); `reset_editor`
re-snapshots the input after a programmatic change (bulk edit, new dimension).
Global context: every section reads and mutates the same RunConfig object, then calls save_config.
"""

import logging  # report unreadable workspace files
from collections.abc import Callable  # editor input factory

import pandas as pd  # editor data
import streamlit as st  # session state + widgets

from agentic_news.catalog import Dimension  # label lookups
from agentic_news.config import RunConfig, config_from_dict, config_to_dict, default_config  # workspace
from agentic_news.settings import Settings  # data_dir
from agentic_news.store import read_json, write_json  # workspace file

log = logging.getLogger(__name__)


def get_config(settings: Settings) -> RunConfig:
    """The session's workspace: data/workspace.json if readable, else the defaults."""
    if "cfg" not in st.session_state:
        data = read_json(settings.data_dir / "workspace.json")
        try:
            st.session_state.cfg = config_from_dict(data) if data else default_config()
        except (KeyError, TypeError, ValueError):  # file from an incompatible version
            log.warning("workspace.json unreadable, starting from defaults")
            st.session_state.cfg = default_config()
        st.session_state.saved = config_to_dict(st.session_state.cfg)
    return st.session_state.cfg


def save_config(cfg: RunConfig, settings: Settings) -> None:
    """Persist the workspace if it changed since the last save."""
    data = config_to_dict(cfg)
    if data != st.session_state.get("saved"):
        write_json(settings.data_dir / "workspace.json", data)
        st.session_state.saved = data


def stable_editor(name: str, make_df: Callable[[], pd.DataFrame], **kwargs: object) -> pd.DataFrame:
    """st.data_editor whose input is snapshotted until reset_editor(name)."""
    version = st.session_state.setdefault(f"{name}__version", 0)
    base = f"{name}__base{version}"
    if base not in st.session_state:
        st.session_state[base] = make_df()
    return st.data_editor(st.session_state[base], key=f"{name}__{version}", **kwargs)


def reset_editor(name: str) -> None:
    """Discard an editor's snapshot so the next render starts from the current config."""
    version = st.session_state.get(f"{name}__version", 0)
    st.session_state.pop(f"{name}__base{version}", None)
    st.session_state[f"{name}__version"] = version + 1


def labels(dim: Dimension) -> dict[str, str]:
    """Option id -> label for one dimension."""
    return {o.id: o.label for o in dim.options}


def as_list(value: object) -> list:
    """Multiselect cell -> list (new editor rows hold None/NaN)."""
    return list(value) if hasattr(value, "__iter__") and not isinstance(value, str) else []


def text(value: object) -> str:
    """Editor text cell -> str (new rows hold None/NaN)."""
    return value.strip() if isinstance(value, str) else ""
