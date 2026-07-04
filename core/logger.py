"""Centralized logging for QuantLab."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_configured = False


def setup_logging(level: str = "INFO", console: bool = True, file: bool = True) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    fmt = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
    formatter = logging.Formatter(fmt)
    root = logging.getLogger("quantlab")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    if console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        root.addHandler(ch)

    if file:
        fh = RotatingFileHandler(
            _LOG_DIR / "quantlab.log",
            maxBytes=50 * 1024 * 1024,
            backupCount=10,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        root.addHandler(fh)


def get_logger(name: str) -> logging.Logger:
    if not _configured:
        setup_logging()
    return logging.getLogger(f"quantlab.{name}")
