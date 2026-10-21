"""Tests for logging_setup.py — log file creation and untruncated, idempotent output.

Global context: the user's rule is that every prompt and LLM output lands in a timestamped log file in full.
"""

import logging  # emit records through the configured logger
from pathlib import Path  # temporary log directory

from agentic_news.logging_setup import LOGGER_NAME, setup_logging  # function under test


def test_long_messages_reach_the_file_in_full_once(tmp_path: Path) -> None:
    """A 100 KB message is written untruncated, and calling setup twice does not duplicate lines."""
    setup_logging(tmp_path, "r1")  # first setup
    path = setup_logging(tmp_path, "r1")  # second setup must replace, not add, handlers
    big = "x" * 100_000 + " é∑"  # long, non-ASCII payload
    logging.getLogger(f"{LOGGER_NAME}.test").info(big)
    for h in logging.getLogger(LOGGER_NAME).handlers:
        h.flush()  # make sure the file handler wrote everything
    text = path.read_text(encoding="utf-8")
    assert path.name == "run_r1.log"  # timestamped run id in the file name
    assert text.count(big) == 1  # full message, exactly once
