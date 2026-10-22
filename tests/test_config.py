"""Tests for config.py — the saved workspace / per-run configuration.

Global context: the dashboard saves a RunConfig to data/workspace.json and each run snapshots it to
runs/<id>/config.json; both must round-trip exactly, including user-added dimensions.
"""

import json  # round-trip through real JSON text
from dataclasses import replace  # add a custom dimension

from agentic_news.catalog import Dimension, Option  # custom dimension
from agentic_news.config import RunConfig, config_from_dict, config_to_dict, default_config  # under test
from agentic_news.prompts import DEFAULT_PROMPT_RULES  # default editable rules


def test_default_config_is_fully_granular() -> None:
    """Defaults: built-in dimensions, one rule per topic, nothing merged, no cap, default prompt rules."""
    cfg = default_config()
    assert [d.key for d in cfg.dimensions][:2] == ["topic", "interval"] and len(cfg.rules) == 24
    assert cfg.merge == [] and cfg.max_cells_per_agent == 0 and cfg.overrides == {}
    assert cfg.prompt_rules == DEFAULT_PROMPT_RULES


def test_round_trip_with_custom_dimension() -> None:
    """to_dict -> JSON -> from_dict restores dataclasses, tuples and custom entries."""
    cfg = default_config()
    region = Dimension("region", "Region", "where", "category", (Option("eu", "Europe", "EU sources"),))
    cfg = replace(cfg, dimensions=[*cfg.dimensions, region], merge=["type"], max_cells_per_agent=5,
                  overrides={"max_parallel_agents": 3}, prompt_rules="custom rules")
    back = config_from_dict(json.loads(json.dumps(config_to_dict(cfg))))
    assert back == cfg and isinstance(back, RunConfig) and back.dimensions[-1].options[0].label == "Europe"
