"""Dashboard section 3: how the selected cells are batched into agents, run settings, prompt rules, Get News.

Local: "merge inside one agent" lists the dimensions whose entries share an agent (none = one agent per cell,
all = one agent for everything); max cells per agent splits big batches. Run settings default to `.env`
(Settings) and only differences are stored as per-run overrides (settings.apply_overrides). The preview shows
agent count and cells per agent; above `confirm_above_agents` an explicit confirmation is required. Widgets use
keys seeded once from the config (https://docs.streamlit.io/develop/concepts/architecture/widget-behavior), so
their state survives reruns.
Global context: launcher.launch_run snapshots this RunConfig and the background CLI executes it.
"""

from statistics import median  # cells-per-agent summary

import streamlit as st  # UI

from agentic_news import launcher  # background run (module attribute, so tests can patch launch_run)
from agentic_news.catalog import build_jobs, expand_rules, validate_dimensions  # cells -> agents
from agentic_news.config import RunConfig  # workspace
from agentic_news.prompts import DEFAULT_PROMPT_RULES  # reset target
from agentic_news.settings import Settings, apply_overrides  # .env defaults + overrides

EFFORTS = ["low", "medium", "high", "xhigh", "max"]  # supported by gpt-6-luna per `codex debug models`
WEB_SEARCH = ["live", "cached", "indexed", "disabled"]  # https://learn.chatgpt.com/docs/config-file/config-basic.md
SETTING_WIDGETS = {  # Settings field -> (label, widget kind, extra args)
    "max_parallel_agents": ("Parallel agents", "int", (1, 256)),
    "codex_model": ("Model", "text", ()),
    "codex_reasoning_effort": ("Reasoning effort", "select", EFFORTS),
    "codex_web_search": ("Web search", "select", WEB_SEARCH),
    "items_per_cell": ("Items per cell", "int", (1, 50)),
    "max_items_per_agent": ("Max items per agent", "int", (1, 1000)),
    "agent_timeout_minutes": ("Timeout per agent (min)", "float", (0.5, 600.0)),
    "agent_max_retries": ("Retries", "int", (0, 10)),
    "confirm_above_agents": ("Confirm above N agents", "int", (1, 100000)),
}


def _seed(key: str, value: object) -> str:
    """Initialise a widget's session-state value once; return the key."""
    st.session_state.setdefault(key, value)
    return key


def _setting_widget(container, name: str, effective: Settings) -> object:
    """One run-setting input bound to session key `set_<name>`."""
    label, kind, extra = SETTING_WIDGETS[name]
    key = _seed(f"set_{name}", getattr(effective, name))
    if kind == "select":
        return container.selectbox(label, extra, key=key)
    if kind == "text":
        return container.text_input(label, key=key)
    return container.number_input(label, *extra, key=key, step=1.0 if kind == "float" else 1)


def render_plan(cfg: RunConfig, base: Settings, active: bool) -> None:
    """Section UI; updates cfg (merge, cap, overrides, prompt rules) and launches runs."""
    dims = cfg.dimensions
    label_of = {d.key: d.label for d in dims}
    effective = apply_overrides(base, cfg.overrides)
    st.session_state["merge"] = [k for k in st.session_state.get("merge", cfg.merge) if k in label_of]
    merge_col, cap_col, par_col = st.columns(3)
    cfg.merge = merge_col.multiselect("Merge inside one agent", list(label_of), format_func=label_of.get, key="merge",
                                      help="Entries of merged dimensions share one agent; none = one agent per cell")
    cfg.max_cells_per_agent = int(cap_col.number_input("Max cells per agent (0 = no limit)", 0, 100000,
                                                       key=_seed("max_cells", cfg.max_cells_per_agent)))
    values = {"max_parallel_agents": _setting_widget(par_col, "max_parallel_agents", effective)}
    with st.expander("Run settings (defaults from .env)"):
        cols = st.columns(3)
        for n, name in enumerate(k for k in SETTING_WIDGETS if k != "max_parallel_agents"):
            values[name] = _setting_widget(cols[n % 3], name, effective)
    with st.expander("Prompt rules (sent to every agent)"):
        if st.button("Reset rules to default"):
            st.session_state.prompt_rules = DEFAULT_PROMPT_RULES
        cfg.prompt_rules = st.text_area("Rules", height=260, key=_seed("prompt_rules", cfg.prompt_rules))
    cfg.overrides = {k: v for k, v in values.items() if v != getattr(base, k)}  # store only what differs from .env
    effective = apply_overrides(base, cfg.overrides)

    errors = validate_dimensions(dims)
    cells = expand_rules(cfg.rules, dims) if not errors else []
    jobs = build_jobs(cells, dims, cfg.merge, cfg.max_cells_per_agent)
    sizes = [len(j.cells) for j in jobs]
    merged = ", ".join(label_of[k] for k in cfg.merge) or "nothing (one agent per cell)"
    st.markdown(f"**{len(cells)}** cell(s) → **{len(jobs)}** agent(s), {effective.max_parallel_agents} at a time · "
                f"merged: {merged}" + (f" · cells per agent min {min(sizes)} / median {median(sizes):g} / "
                                       f"max {max(sizes)}" if sizes else ""))
    if jobs:
        st.caption("Agents: " + "; ".join(j.label for j in jobs[:5]) + (" …" if len(jobs) > 5 else ""))
    confirmed = len(jobs) <= effective.confirm_above_agents or st.checkbox(
        f"Yes, launch {len(jobs)} agents (above the confirmation threshold of {effective.confirm_above_agents})")
    if st.button("Get News", type="primary", key="get_news",
                 disabled=active or bool(errors) or not jobs or not confirmed):
        launcher.launch_run(cfg, base)
        st.rerun()
