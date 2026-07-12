import pytest
from datacompare.normalize.decimals import round_half_up

@pytest.mark.parametrize("x,places,expected", [
    (2.5, 0, 3.0),          # NOT 2.0 (banker's rounding)
    (0.5, 0, 1.0),
    (1.5, 0, 2.0),
    (12.345, 2, 12.35),
    (0.001234, 2, 0.00),
    (12.3456, 2, 12.35),
    (-2.5, 0, -3.0),
    (1.005, 2, 1.01),       # classic float trap; Decimal handles it
    (99.995, 2, 100.00),
])
def test_round_half_up(x, places, expected):
    assert round_half_up(x, places) == expected

def test_returns_float_type():
    assert isinstance(round_half_up(1.5, 0), float)
