"""Application-wide logging setup."""

from __future__ import annotations

import logging
import logging.handlers
import sys

from etools.config import get_log_dir

_FMT = "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s"
_DATEFMT = "%H:%M:%S"
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUPS = 3


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure root logger with console + rotating file handlers."""
    root = logging.getLogger()
    if root.handlers:
        return logging.getLogger("etools")

    root.setLevel(level)
    formatter = logging.Formatter(_FMT, datefmt=_DATEFMT)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    log_dir = get_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "etools.log",
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUPS,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(file_handler)

    return logging.getLogger("etools")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"etools.{name}")
