"""Unified logging configuration for workflow backend."""
from __future__ import annotations

import logging
import os
from pathlib import Path

# Log directory — configurable via LOG_DIR env var for Docker
LOG_DIR = Path(os.getenv("LOG_DIR", str(Path(__file__).parent.parent / "logs")))
LOG_DIR.mkdir(exist_ok=True)

# Prevent duplicate handlers
_configured_loggers: set[str] = set()


def setup_logger(name: str, filename: str) -> logging.Logger:
    """Setup a logger with file and console handlers.

    Args:
        name: Logger name (e.g., 'sse', 'worker', 'api')
        filename: Log file name (e.g., 'sse.log')

    Returns:
        Configured logger instance
    """
    if name in _configured_loggers:
        return logging.getLogger(name)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # Prevent duplicate logs

    # File handler
    fh = logging.FileHandler(LOG_DIR / filename, encoding='utf-8')
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] [%(levelname)s] %(message)s"
    ))

    # Console handler
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(message)s"
    ))

    logger.addHandler(fh)
    logger.addHandler(sh)

    _configured_loggers.add(name)
    return logger


# Pre-configured loggers
def get_sse_logger() -> logging.Logger:
    """Logger for SSE events (FastAPI side)."""
    return setup_logger("sse", "sse.log")


def get_worker_logger() -> logging.Logger:
    """Logger for worker activities."""
    return setup_logger("worker", "worker.log")


def get_api_logger() -> logging.Logger:
    """Logger for API requests."""
    return setup_logger("api", "api.log")
