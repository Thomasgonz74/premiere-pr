"""Lecture de la structure du marché : swings, tendance, supports/résistances.

Aucun indicateur externe — uniquement les prix, comme sur un graphique nu.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TrendReading:
    direction: int      # +1 haussier, -1 baissier, 0 range/indécis
    label: str


@dataclass(frozen=True)
class Level:
    price: float
    kind: str           # "support" ou "resistance"
    touches: int        # nombre de fois où le niveau a réagi


def find_swings(df: pd.DataFrame, lookback: int = 2) -> tuple[list[float], list[float]]:
    """Détecte les points pivots (fractales) : un plus-haut/plus-bas entouré de
    `lookback` bougies plus basses/hautes de chaque côté."""
    highs: list[float] = []
    lows: list[float] = []
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    for i in range(lookback, len(df) - lookback):
        if h[i] == max(h[i - lookback : i + lookback + 1]):
            highs.append(float(h[i]))
        if l[i] == min(l[i - lookback : i + lookback + 1]):
            lows.append(float(l[i]))
    return highs, lows


def read_trend(df: pd.DataFrame, lookback: int = 2) -> TrendReading:
    """Tendance par la structure : sommets/creux ascendants (HH/HL) → haussier,
    descendants (LH/LL) → baissier, sinon range."""
    highs, lows = find_swings(df, lookback)
    if len(highs) < 2 or len(lows) < 2:
        return TrendReading(0, "indetermine")
    hh = highs[-1] > highs[-2]
    hl = lows[-1] > lows[-2]
    lh = highs[-1] < highs[-2]
    ll = lows[-1] < lows[-2]
    if hh and hl:
        return TrendReading(+1, "haussier (HH/HL)")
    if lh and ll:
        return TrendReading(-1, "baissier (LH/LL)")
    return TrendReading(0, "range")


def find_levels(df: pd.DataFrame, tolerance_pct: float = 0.05, lookback: int = 2) -> list[Level]:
    """Regroupe les swings proches en niveaux de support/résistance.

    tolerance_pct : largeur de regroupement en % du prix (0.05 % ≈ zone S/R).
    """
    highs, lows = find_swings(df, lookback)
    last_price = float(df["close"].iloc[-1])
    tol = last_price * tolerance_pct / 100.0

    def cluster(points: list[float], kind: str) -> list[Level]:
        levels: list[Level] = []
        for p in sorted(points):
            if levels and abs(p - levels[-1].price) <= tol:
                prev = levels[-1]
                merged = (prev.price * prev.touches + p) / (prev.touches + 1)
                levels[-1] = Level(merged, kind, prev.touches + 1)
            else:
                levels.append(Level(p, kind, 1))
        return levels

    resistances = [lv for lv in cluster(highs, "resistance") if lv.price >= last_price]
    supports = [lv for lv in cluster(lows, "support") if lv.price <= last_price]
    # Niveaux les plus proches du prix d'abord — c'est eux qui comptent en scalping.
    resistances.sort(key=lambda lv: lv.price - last_price)
    supports.sort(key=lambda lv: last_price - lv.price)
    return supports + resistances


def nearest_level(levels: list[Level], price: float, kind: str) -> Level | None:
    candidates = [lv for lv in levels if lv.kind == kind]
    if not candidates:
        return None
    return min(candidates, key=lambda lv: abs(lv.price - price))


def distance_in_atr(df: pd.DataFrame, price_a: float, price_b: float, period: int = 14) -> float:
    """Distance entre deux prix exprimée en ATR (volatilité récente) —
    permet des seuils indépendants de l'instrument."""
    atr = average_true_range(df, period)
    if atr <= 0:
        return float("inf")
    return abs(price_a - price_b) / atr


def average_true_range(df: pd.DataFrame, period: int = 14) -> float:
    """ATR simple, calculé à la main sur les dernières bougies."""
    if len(df) < period + 1:
        return 0.0
    h = df["high"].to_numpy()[-period - 1 :]
    l = df["low"].to_numpy()[-period - 1 :]
    c = df["close"].to_numpy()[-period - 1 :]
    trs = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return float(trs.mean())
