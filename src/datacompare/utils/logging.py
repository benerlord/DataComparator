"""structlog configuration."""
from __future__ import annotations
import logging
import sys
from pathlib import Path
import structlog


def configure_logging(level: str = "INFO", log_file: Path | None = None) -> None:
    level_num = getattr(logging, level.upper(), logging.INFO)

    # Reset root logger to avoid duplicate handlers on repeated configure calls (e.g., in tests)
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    root.setLevel(level_num)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(stderr_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(file_handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_num),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str = "datacompare"):
    return structlog.get_logger(name)
