"""ChartAnalystAgent : lit les chandelles du timeframe de signal (M5).

Un analyste par symbole actif. Il ne connaît ni le compte ni le risque :
il ne fait que lire le graphique et proposer des idées orientées.
"""

from __future__ import annotations

import logging

from ..analysis.candles import scan_candles
from ..analysis.structure import average_true_range
from ..broker.base import Broker
from ..config import AppConfig
from .base import TradeIdea

log = logging.getLogger(__name__)


class ChartAnalystAgent:
    def __init__(self, broker: Broker, config: AppConfig) -> None:
        self.broker = broker
        self.config = config

    def analyse(self, symbol: str) -> TradeIdea | None:
        df = self.broker.candles(symbol, self.config.trading.signal_timeframe, 100)
        if df is None or len(df) < 20:
            return None
        patterns = scan_candles(df)
        if not patterns:
            return None
        # Direction nette des patterns détectés (pondérée par leur force).
        weight = sum(p.direction * p.strength for p in patterns)
        if weight == 0:
            return None
        direction = 1 if weight > 0 else -1
        idea = TradeIdea(
            symbol=symbol,
            direction=direction,
            patterns=[p for p in patterns if p.direction == direction],
            last_price=float(df["close"].iloc[-1]),
            atr=average_true_range(df),
        )
        log.debug("%s : %s → %s", symbol,
                  [p.pattern for p in idea.patterns],
                  "ACHAT" if direction > 0 else "VENTE")
        return idea
