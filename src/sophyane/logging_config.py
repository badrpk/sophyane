"""Central Sophyane logging configuration."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from sophyane.config import LOG_DIR, ensure_directories


def configure_logging(verbose: bool = False) -> logging.Logger:
    ensure_directories()

    logger = logging.getLogger("sophyane")

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    file_handler = RotatingFileHandler(
        LOG_DIR / "sophyane.log",
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(
        logging.DEBUG if verbose else logging.WARNING
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger
