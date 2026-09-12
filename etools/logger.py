"""Application-wide logging setup."""

from __future__ import annotations

import logging
import sys

from etools.config import get_log_dir

_FMT = "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s"
_DATEFMT = "%H:%M:%S"


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
    file_handler = logging.FileHandler(log_dir / "etools.log", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(file_handler)

    return logging.getLogger("etools")


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"etools.{name}")
