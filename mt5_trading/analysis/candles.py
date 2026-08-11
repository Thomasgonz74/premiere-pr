"""Détection de figures de chandelles japonaises (lecture de graphique pure).

Chaque détecteur travaille sur un DataFrame OHLC (colonnes open, high, low,
close) et examine les dernières bougies clôturées. Il renvoie un
CandleSignal orienté (+1 achat / -1 vente) avec une force de 1 à 3.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class CandleSignal:
    pattern: str
    direction: int   # +1 haussier, -1 baissier
    strength: int    # 1 faible, 2 moyen, 3 fort


def _body(c: pd.Series) -> float:
    return abs(c["close"] - c["open"])


def _range(c: pd.Series) -> float:
    return max(c["high"] - c["low"], 1e-12)


def _upper_wick(c: pd.Series) -> float:
    return c["high"] - max(c["open"], c["close"])


def _lower_wick(c: pd.Series) -> float:
    return min(c["open"], c["close"]) - c["low"]


def _bullish(c: pd.Series) -> bool:
    return c["close"] > c["open"]


def _bearish(c: pd.Series) -> bool:
    return c["close"] < c["open"]


def detect_hammer(df: pd.DataFrame) -> CandleSignal | None:
    """Marteau : longue mèche basse, petit corps en haut — rejet des vendeurs."""
    c = df.iloc[-1]
    if _lower_wick(c) >= 2.0 * _body(c) and _upper_wick(c) <= 0.2 * _range(c):
        if _body(c) / _range(c) <= 0.4:
            return CandleSignal("marteau", +1, 2)
    return None


def detect_shooting_star(df: pd.DataFrame) -> CandleSignal | None:
    """Étoile filante : longue mèche haute, petit corps en bas — rejet des acheteurs."""
    c = df.iloc[-1]
    if _upper_wick(c) >= 2.0 * _body(c) and _lower_wick(c) <= 0.2 * _range(c):
        if _body(c) / _range(c) <= 0.4:
            return CandleSignal("etoile_filante", -1, 2)
    return None


def detect_engulfing(df: pd.DataFrame) -> CandleSignal | None:
    """Avalement : le corps de la dernière bougie englobe le corps précédent."""
    if len(df) < 2:
        return None
    prev, c = df.iloc[-2], df.iloc[-1]
    if _body(prev) <= 0:
        return None
    engulfs = (
        max(c["open"], c["close"]) >= max(prev["open"], prev["close"])
        and min(c["open"], c["close"]) <= min(prev["open"], prev["close"])
        and _body(c) > _body(prev)
    )
    if not engulfs:
        return None
    if _bullish(c) and _bearish(prev):
        return CandleSignal("avalement_haussier", +1, 3)
    if _bearish(c) and _bullish(prev):
        return CandleSignal("avalement_baissier", -1, 3)
    return None


def detect_doji(df: pd.DataFrame) -> CandleSignal | None:
    """Doji : indécision. Signal faible, orienté par la bougie précédente
    (un doji après une forte impulsion suggère l'essoufflement)."""
    if len(df) < 2:
        return None
    prev, c = df.iloc[-2], df.iloc[-1]
    if _body(c) / _range(c) <= 0.1:
        if _bullish(prev) and _body(prev) / _range(prev) > 0.6:
            return CandleSignal("doji_sommet", -1, 1)
        if _bearish(prev) and _body(prev) / _range(prev) > 0.6:
            return CandleSignal("doji_creux", +1, 1)
    return None


def detect_marubozu(df: pd.DataFrame) -> CandleSignal | None:
    """Marubozu : bougie pleine sans mèches — conviction directionnelle."""
    c = df.iloc[-1]
    if _body(c) / _range(c) >= 0.9:
        return CandleSignal("marubozu", +1 if _bullish(c) else -1, 2)
    return None


def detect_three_soldiers_crows(df: pd.DataFrame) -> CandleSignal | None:
    """Trois soldats blancs / trois corbeaux noirs : trois bougies pleines
    consécutives dans le même sens, clôtures en progression."""
    if len(df) < 3:
        return None
    a, b, c = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    full = all(_body(x) / _range(x) >= 0.55 for x in (a, b, c))
    if not full:
        return None
    if all(_bullish(x) for x in (a, b, c)) and a["close"] < b["close"] < c["close"]:
        return CandleSignal("trois_soldats", +1, 3)
    if all(_bearish(x) for x in (a, b, c)) and a["close"] > b["close"] > c["close"]:
        return CandleSignal("trois_corbeaux", -1, 3)
    return None


def detect_pin_bar(df: pd.DataFrame) -> CandleSignal | None:
    """Pin bar : mèche dominante (≥ 66 % du range) qui « pointe » le rejet."""
    c = df.iloc[-1]
    rng = _range(c)
    if _lower_wick(c) / rng >= 0.66:
        return CandleSignal("pin_bar_haussier", +1, 2)
    if _upper_wick(c) / rng >= 0.66:
        return CandleSignal("pin_bar_baissier", -1, 2)
    return None


def detect_inside_bar_breakout(df: pd.DataFrame) -> CandleSignal | None:
    """Inside bar puis cassure : compression (bougie -2 dans le range de -3)
    résolue par la clôture de la dernière bougie hors du range mère."""
    if len(df) < 3:
        return None
    mother, inside, brk = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    is_inside = inside["high"] <= mother["high"] and inside["low"] >= mother["low"]
    if not is_inside:
        return None
    if brk["close"] > mother["high"]:
        return CandleSignal("inside_bar_cassure_haut", +1, 2)
    if brk["close"] < mother["low"]:
        return CandleSignal("inside_bar_cassure_bas", -1, 2)
    return None


ALL_DETECTORS = (
    detect_engulfing,
    detect_three_soldiers_crows,
    detect_hammer,
    detect_shooting_star,
    detect_marubozu,
    detect_pin_bar,
    detect_inside_bar_breakout,
    detect_doji,
)


def scan_candles(df: pd.DataFrame) -> list[CandleSignal]:
    """Applique tous les détecteurs sur les dernières bougies clôturées."""
    if df is None or len(df) < 3:
        return []
    signals: list[CandleSignal] = []
    for detector in ALL_DETECTORS:
        sig = detector(df)
        if sig is not None:
            signals.append(sig)
    return signals
