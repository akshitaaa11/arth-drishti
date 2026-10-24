from __future__ import annotations

import logging
from pathlib import Path


def get_logger(name: str, *, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    logger.propagate = False
    return logger


def configure_logging(log_dir: str | Path | None = None) -> None:
    if log_dir is not None:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
