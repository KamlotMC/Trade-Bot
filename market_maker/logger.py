"""
Logging setup for the Meowcoin Market Maker bot.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from market_maker.config import LoggingConfig


def setup_logger(name: str, cfg: LoggingConfig) -> logging.Logger:
    """Create and configure a logger with console and file handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, cfg.level.upper(), logging.INFO))
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    if cfg.console:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    # File handler
    if cfg.file:
        log_dir = os.path.dirname(cfg.file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        fh = RotatingFileHandler(
            cfg.file,
            maxBytes=cfg.max_file_size_mb * 1024 * 1024,
            backupCount=cfg.backup_count,
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger
