"""Tests de la couche d'analyse graphique (chandelles, structure, SMC)."""

import pandas as pd
import pytest

from mt5_trading.analysis.candles import (
    detect_engulfing,
    detect_hammer,
    detect_shooting_star,
    detect_three_soldiers_crows,
    scan_candles,
)
from mt5_trading.analysis.smc import detect_fvg, find_order_blocks
from mt5_trading.analysis.structure import average_true_range, find_levels, read_trend


def make_df(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


NEUTRAL = [100.0, 100.5, 99.5, 100.2]


def test_hammer_detected():
    df = make_df([NEUTRAL, NEUTRAL, [100.0, 100.3, 97.0, 100.2]])
    assert detect_hammer(df).direction == +1


def test_shooting_star_detected():
    df = make_df([NEUTRAL, NEUTRAL, [100.0, 103.0, 99.9, 99.95]])
    sig = detect_shooting_star(df)
    assert sig is not None and sig.direction == -1


def test_bullish_engulfing():
    df = make_df([NEUTRAL, [100.5, 100.6, 99.4, 99.6], [99.5, 101.2, 99.3, 101.0]])
    sig = detect_engulfing(df)
    assert sig is not None and sig.direction == +1 and sig.strength == 3


def test_three_white_soldiers():
    df = make_df([
        [100.0, 100.6, 99.9, 100.5],
        [100.5, 101.2, 100.4, 101.1],
        [101.1, 101.9, 101.0, 101.8],
    ])
    sig = detect_three_soldiers_crows(df)
    assert sig is not None and sig.direction == +1


def test_scan_returns_empty_on_flat_history():
    df = make_df([NEUTRAL] * 10)
    # Un marché plat sans figure directionnelle ne doit pas générer d'avalement.
    assert all(s.pattern not in ("avalement_haussier", "avalement_baissier")
               for s in scan_candles(df))


def test_trend_uptrend():
    rows = []
    price = 100.0
    for i in range(30):
        # Vagues montantes : creux et sommets ascendants.
        wave = (i % 5) - 2
        o = price + wave * 0.3
        c = o + 0.4
        rows.append([o, c + 0.2, o - 0.2, c])
        price += 0.25
    trend = read_trend(make_df(rows))
    assert trend.direction == +1


def test_levels_split_around_price():
    rows = [[100.0 + (i % 4) * 0.5, 100.6 + (i % 4) * 0.5,
             99.8 + (i % 4) * 0.5, 100.3 + (i % 4) * 0.5] for i in range(40)]
    levels = find_levels(make_df(rows))
    price = make_df(rows)["close"].iloc[-1]
    assert all(lv.price <= price for lv in levels if lv.kind == "support")
    assert all(lv.price >= price for lv in levels if lv.kind == "resistance")


def test_atr_positive():
    df = make_df([[100, 101, 99, 100.5]] * 20)
    assert average_true_range(df) == pytest.approx(2.0)


def test_bullish_fvg_detected():
    rows = [NEUTRAL] * 5 + [
        [100.0, 100.5, 99.8, 100.4],   # bougie A (high=100.5)
        [100.4, 103.0, 100.3, 102.8],  # impulsion
        [102.9, 103.5, 101.0, 101.2],  # bougie C (low=101.0 > 100.5 → FVG)
    ]
    zones = detect_fvg(make_df(rows))
    assert any(z.direction == +1 for z in zones)


def test_order_block_detected():
    rows = [NEUTRAL] * 5 + [
        [100.5, 100.6, 99.9, 100.0],   # bougie baissière = order block
        [100.0, 102.0, 99.9, 101.8],   # impulsion haussière
        [101.9, 103.0, 100.8, 102.5],  # low 100.8 > high OB 100.6 → FVG confirmé
    ]
    blocks = find_order_blocks(make_df(rows))
    assert any(b.direction == +1 for b in blocks)
