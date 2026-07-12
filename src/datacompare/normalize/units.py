"""Parse '<number> <unit>' strings and convert to a target unit."""
from __future__ import annotations
import re
from dataclasses import dataclass

UNIT_TABLES: dict[str, dict[str, float]] = {
    "storage": {
        "B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3,
        "TB": 1024**4, "PB": 1024**5,
    },
    "time": {
        "ms": 1, "s": 1_000, "min": 60_000,
        "h": 3_600_000, "d": 86_400_000,
    },
    "length": {"mm": 1, "cm": 10, "m": 1_000, "km": 1_000_000},
    "mass": {"mg": 1, "g": 1_000, "kg": 1_000_000, "t": 1_000_000_000},
}

_UNIT_PATTERN = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*([a-zA-Z]+)\s*$"
)


@dataclass(frozen=True)
class UnitError:
    original: str
    reason: str  # "no_unit_pattern" | "unknown_unit" | "unknown_category"


def parse_and_convert(s: str, category: str, target_unit: str) -> float | UnitError:
    match = _UNIT_PATTERN.match(s)
    if not match:
        return UnitError(original=s, reason="no_unit_pattern")
    value, unit = float(match.group(1)), match.group(2)
    table = UNIT_TABLES.get(category)
    if table is None:
        return UnitError(original=s, reason="unknown_category")
    lookup = {k.lower(): v for k, v in table.items()}
    unit_lower = unit.lower()
    target_lower = target_unit.lower()
    if unit_lower not in lookup or target_lower not in lookup:
        return UnitError(original=s, reason="unknown_unit")
    return value * lookup[unit_lower] / lookup[target_lower]
