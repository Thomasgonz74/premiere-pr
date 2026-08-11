"""TrendContextAgent : lit le contexte multi-timeframe d'un symbole.

Biais mensuel (MN1) et journalier (D1) pour la direction de fond,
micro-tendance (M15) pour le timing, niveaux S/R pour placer les stops.
Pure lecture de structure — aucun indicateur.
"""

from __future__ import annotations

import logging

from ..analysis.structure import find_levels, read_trend
from ..broker.base import Broker
from ..config import AppConfig
from .base import MarketBias

log = logging.getLogger(__name__)


class TrendContextAgent:
    def __init__(self, broker: Broker, config: AppConfig) -> None:
        self.broker = broker
        self.config = config

    def read(self, symbol: str) -> MarketBias | None:
        tf = self.config.trading
        micro_df = self.broker.candles(symbol, tf.context_timeframe, 120)
        daily_df = self.broker.candles(symbol, tf.daily_timeframe, 60)
        monthly_df = self.broker.candles(symbol, tf.monthly_timeframe, 24)
        if micro_df is None or daily_df is None:
            return None

        micro = read_trend(micro_df)
        daily = read_trend(daily_df)
        monthly = read_trend(monthly_df) if monthly_df is not None and len(monthly_df) >= 8 \
            else read_trend(daily_df, lookback=3)
        # Les niveaux qui comptent pour un scalp : structure M15 récente.
        levels = find_levels(micro_df)

        bias = MarketBias(symbol=symbol, micro=micro, daily=daily,
                          monthly=monthly, levels=levels)
        log.debug("%s : micro=%s, daily=%s, monthly=%s, %d niveaux",
                  symbol, micro.label, daily.label, monthly.label, len(levels))
        return bias
