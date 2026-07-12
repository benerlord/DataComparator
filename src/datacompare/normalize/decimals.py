"""Decimal rounding with ROUND_HALF_UP (not banker's)."""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(x: float, places: int) -> float:
    """Round half away from zero (business rounding), not Python's banker's rounding."""
    q = Decimal(10) ** -places
    return float(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))
