"""MarketScannerAgent : filtre la watchlist en conditions tradables.

Un symbole n'est actif que si :
  - la session le permet (Londres / New York) ;
  - le spread courant reste sous le plafond défini pour l'instrument ;
  - la volatilité récente (ATR) est suffisante pour viser un TP en < 30 min.
"""

from __future__ import annotations

import logging

from ..analysis.structure import average_true_range
from ..broker.base import Broker
from ..config import AppConfig, SymbolSpec

log = logging.getLogger(__name__)


class MarketScannerAgent:
    def __init__(self, broker: Broker, config: AppConfig) -> None:
        self.broker = broker
        self.config = config

    def in_session(self) -> bool:
        hour = self.broker.now().hour
        return any(start <= hour < end for start, end in self.config.trading.sessions_utc)

    def scan(self) -> list[SymbolSpec]:
        if not self.in_session():
            log.debug("Hors session Londres/NY : scan suspendu.")
            return []
        active: list[SymbolSpec] = []
        for spec in self.config.watchlist:
            info = self.broker.symbol_info(spec.name)
            if info is None:
                log.warning("Symbole %s introuvable chez le broker (adaptez config.py).", spec.name)
                continue
            if info.spread_points > spec.max_spread_points:
                log.debug("%s écarté : spread %.1f > %.1f", spec.name,
                          info.spread_points, spec.max_spread_points)
                continue
            df = self.broker.candles(spec.name, self.config.trading.signal_timeframe, 60)
            if df is None or len(df) < 30:
                continue
            atr = average_true_range(df)
            # Le TP (~1.5 ATR) doit dépasser nettement le coût du spread,
            # sinon le scalp part perdant d'avance.
            if atr <= info.spread_points * info.point * 3:
                log.debug("%s écarté : volatilité trop faible pour couvrir le spread.", spec.name)
                continue
            active.append(spec)
        return active
