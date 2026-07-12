"""Task config validation (config + connectivity + column existence)."""
from __future__ import annotations
from datacompare.config.models import TaskConfig, AnyConnection
from datacompare.config.errors import ConfigError
from datacompare.runner import _build_source


def validate_task(task: TaskConfig, connections: dict[str, AnyConnection]) -> list[str]:
    """Return list of issues (empty = OK). Raises ConfigError only on connect failures."""
    issues: list[str] = []

    for side in ("left", "right"):
        cfg = task.sources[side]
        try:
            src = _build_source(cfg, connections, side_name=side)
        except ConfigError as e:
            issues.append(f"{side}: {e}")
            continue

        try:
            cols = src.columns()
        except Exception as e:
            issues.append(f"{side}: cannot read columns — {e}")
            src.close()
            continue

        for k in task.match.keys:
            wanted = getattr(k, side)
            if wanted not in cols:
                issues.append(
                    f"{side}: match key column '{wanted}' not found. "
                    f"Available: {cols[:20]}"
                )
        for f in task.compare.fields:
            wanted = getattr(f, side)
            if wanted not in cols:
                issues.append(
                    f"{side}: compare field column '{wanted}' not found. "
                    f"Available: {cols[:20]}"
                )
        src.close()
    return issues
