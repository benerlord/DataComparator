"""Type coercion with sentinel-on-failure semantics (never raises)."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from dateutil import parser as _dtparser


@dataclass(frozen=True)
class CoerceError:
    original: str
    target: str


def coerce_type(
    s: str | None,
    as_type: Literal["datetime", "int", "float", "string"] | None,
    datetime_format: str | None = None,
) -> Any:
    if s is None:
        return None
    if as_type is None:
        return s
    try:
        if as_type == "int":
            return int(s)
        if as_type == "float":
            return float(s)
        if as_type == "string":
            return s
        if as_type == "datetime":
            if datetime_format:
                return datetime.strptime(s, datetime_format)
            return _dtparser.parse(s)
    except (ValueError, TypeError, OverflowError):
        return CoerceError(original=s, target=as_type)
    return CoerceError(original=s, target=as_type)
