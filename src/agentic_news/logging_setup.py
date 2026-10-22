"""Logging: one timestamped log file per run plus the terminal, both in real time and never truncated.

Local: configures the `agentic_news` logger with a UTF-8 FileHandler (logs/run_<run_id>.log) and a stdout
StreamHandler (https://docs.python.org/3/howto/logging-cookbook.html#logging-to-multiple-destinations).
Global context: the runner logs every full prompt, every Codex JSONL event and every final answer through this
logger, so a run can be audited afterwards from the log file alone.
"""

import logging  # standard library logging
import sys  # stdout stream for the terminal handler
from pathlib import Path  # log directory

LOGGER_NAME = "agentic_news"  # parent of every module logger (agentic_news.runner, ...)
_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s"  # millisecond timestamps
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(logs_dir: Path, run_id: str) -> Path:
    """Attach file + terminal handlers (replacing old ones) and return the log file path."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"run_{run_id}.log"
    if hasattr(sys.stdout, "reconfigure"):
        # On Windows only the console device is UTF-8; pipes and files (scheduler, redirects) use the ANSI code
        # page, e.g. cp1252 (https://docs.python.org/3/library/sys.html#sys.stdout)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    formatter = logging.Formatter(_FORMAT, _DATEFMT)
    logger = logging.getLogger(LOGGER_NAME)
    for old in list(logger.handlers):  # idempotent: repeated runs in one process don't duplicate lines
        logger.removeHandler(old)
        old.close()
    for handler in (logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stdout)):
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # don't double-print through the root logger (e.g. under Streamlit)
    return log_path
