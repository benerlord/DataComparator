"""String normalization: null equivalents, whitespace collapse, case fold."""
from __future__ import annotations
import re

_WS_RE = re.compile(r"\s+")


def normalize_string(
    s: str | None,
    ignore_whitespace: bool = False,
    ignore_case: bool = False,
    null_equivalents: list[str] | None = None,
) -> str | None:
    if s is None:
        return None
    if null_equivalents and s in null_equivalents:
        return None
    if ignore_whitespace:
        s = _WS_RE.sub(" ", s.strip())
    if ignore_case:
        s = s.casefold()
    return s
