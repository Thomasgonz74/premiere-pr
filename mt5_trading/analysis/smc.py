"""Concepts « Smart Money » (SMC) — inspirés de la méthode documentée de
Kasper Trading (tradingkasper.com) : Order Blocks, Fair Value Gaps et zone
Fibonacci OTE.

Références publiques :
  - Order Block : dernière bougie opposée avant une impulsion, valide
    uniquement si l'impulsion laisse un vide de liquidité (FVG).
  - Bougie englobante : signal fort seulement si elle clôture dans la zone
    OTE (retracement Fibonacci 0,62–0,86) du dernier mouvement.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .structure import find_swings


@dataclass(frozen=True)
class Zone:
    kind: str        # "fvg" ou "order_block"
    direction: int   # +1 zone de demande (achat), -1 zone d'offre (vente)
    top: float
    bottom: float

    def contains(self, price: float) -> bool:
        return self.bottom <= price <= self.top


def detect_fvg(df: pd.DataFrame, max_lookback: int = 30) -> list[Zone]:
    """Fair Value Gaps : vide entre la mèche de la bougie n-2 et celle de n,
    laissé par une impulsion (la bougie n-1). Zones encore non comblées."""
    found: list[tuple[int, Zone]] = []
    start = max(2, len(df) - max_lookback)
    for i in range(start, len(df)):
        a, c = df.iloc[i - 2], df.iloc[i]
        # FVG haussier : le plus bas de la bougie n reste au-dessus du plus
        # haut de la bougie n-2.
        if c["low"] > a["high"]:
            found.append((i, Zone("fvg", +1, float(c["low"]), float(a["high"]))))
        # FVG baissier : symétrique.
        if c["high"] < a["low"]:
            found.append((i, Zone("fvg", -1, float(a["low"]), float(c["high"]))))
    # Écarte les gaps comblés par le prix APRÈS leur formation.
    still_open = []
    for i, z in found:
        later = df.iloc[i + 1 :]
        if len(later) == 0:
            filled = False
        elif z.direction > 0:
            filled = bool((later["low"] <= z.bottom).any())
        else:
            filled = bool((later["high"] >= z.top).any())
        if not filled:
            still_open.append(z)
    return still_open


def find_order_blocks(df: pd.DataFrame, max_lookback: int = 40) -> list[Zone]:
    """Order Block : dernière bougie opposée avant une impulsion qui laisse
    un FVG. On garde les zones (corps de la bougie) proches du prix."""
    blocks: list[Zone] = []
    start = max(3, len(df) - max_lookback)
    for i in range(start, len(df) - 2):
        ob = df.iloc[i]
        nxt, gap_check = df.iloc[i + 1], df.iloc[i + 2]
        body_top = float(max(ob["open"], ob["close"]))
        body_bottom = float(min(ob["open"], ob["close"]))
        # OB haussier : bougie baissière, puis impulsion haussière laissant un FVG.
        if ob["close"] < ob["open"] and nxt["close"] > nxt["open"] \
                and gap_check["low"] > ob["high"]:
            blocks.append(Zone("order_block", +1, body_top, body_bottom))
        # OB baissier : bougie haussière, puis impulsion baissière laissant un FVG.
        if ob["close"] > ob["open"] and nxt["close"] < nxt["open"] \
                and gap_check["high"] < ob["low"]:
            blocks.append(Zone("order_block", -1, body_top, body_bottom))
    return blocks


def in_ote_zone(df: pd.DataFrame, direction: int, low_ratio: float = 0.62,
                high_ratio: float = 0.86) -> bool:
    """Zone OTE (Optimal Trade Entry) : le prix a retracé 62–86 % du dernier
    swing dans le sens du trade envisagé."""
    highs, lows = find_swings(df)
    if not highs or not lows:
        return False
    price = float(df["close"].iloc[-1])
    if direction > 0:
        leg_low, leg_high = lows[-1], highs[-1]
        if leg_high <= leg_low:
            return False
        retrace = (leg_high - price) / (leg_high - leg_low)
    else:
        leg_low, leg_high = lows[-1], highs[-1]
        if leg_high <= leg_low:
            return False
        retrace = (price - leg_low) / (leg_high - leg_low)
    return low_ratio <= retrace <= high_ratio


def zone_confluence(df: pd.DataFrame, direction: int) -> list[Zone]:
    """Zones SMC (FVG + Order Blocks) dans le sens du trade contenant le prix."""
    price = float(df["close"].iloc[-1])
    zones = detect_fvg(df) + find_order_blocks(df)
    return [z for z in zones if z.direction == direction and z.contains(price)]
