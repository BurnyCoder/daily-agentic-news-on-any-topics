"""Run configuration: everything the user can customize, saved as JSON.

Local: `RunConfig` bundles the dimensions (entries and whole dimensions are editable), the selection rules, the
batching choice (which dimensions are merged inside one agent, max cells per agent), per-run setting overrides
(parallelism, model, effort, ...; see settings.apply_overrides) and the editable prompt rules. `config_to_dict`
/ `config_from_dict` round-trip it through JSON (dataclasses.asdict,
https://docs.python.org/3/library/dataclasses.html#dataclasses.asdict).
Global context: the dashboard edits and saves it to data/workspace.json; every run snapshots it to
runs/<run_id>/config.json, which the CLI/pipeline executes and the results view reads for labels.
"""

from dataclasses import asdict, dataclass, field  # config record + JSON conversion

from agentic_news.catalog import Dimension, Option, default_dimensions, default_rules  # cell space
from agentic_news.prompts import DEFAULT_PROMPT_RULES  # editable rules default


@dataclass
class RunConfig:
    """What to search (dimensions + rules), how to batch it into agents, and run-level overrides."""

    dimensions: list[Dimension]
    rules: list[dict]
    merge: list[str] = field(default_factory=list)  # dimension keys merged inside one agent ([] = one per cell)
    max_cells_per_agent: int = 0  # split bigger agent batches (0 = no limit)
    overrides: dict[str, object] = field(default_factory=dict)  # Settings field -> value for this run
    prompt_rules: str = DEFAULT_PROMPT_RULES  # the "Rules" section of every prompt


def default_config() -> RunConfig:
    """Built-in dimensions, one unchecked rule per topic, fully granular batching."""
    dims = default_dimensions()
    return RunConfig(dimensions=dims, rules=default_rules(dims))


def config_to_dict(cfg: RunConfig) -> dict:
    """JSON-ready dict (nested dataclasses become dicts)."""
    return asdict(cfg)


def config_from_dict(data: dict) -> RunConfig:
    """Rebuild a RunConfig from config_to_dict output (lists back to tuples, dicts back to dataclasses)."""
    dims = [Dimension(**{**d, "options": tuple(Option(**o) for o in d["options"])}) for d in data["dimensions"]]
    return RunConfig(dimensions=dims, rules=data.get("rules", []), merge=list(data.get("merge", [])),
                     max_cells_per_agent=int(data.get("max_cells_per_agent", 0)),
                     overrides=dict(data.get("overrides", {})),
                     prompt_rules=data.get("prompt_rules", DEFAULT_PROMPT_RULES))
