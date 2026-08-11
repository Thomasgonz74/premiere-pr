"""PositionSupervisorAgent : gère chaque position ouverte jusqu'à sa sortie.

Règles :
  - durée de vie maximale de 30 minutes (exigence scalping) → fermeture forcée ;
  - passage du SL au point d'entrée (« breakeven ») dès +1R atteint ;
  - fermeture immédiate de tout si l'arrêt journalier est déclenché.
"""

from __future__ import annotations

import logging

from ..broker.base import Broker, Position
from ..config import AppConfig

log = logging.getLogger(__name__)


class PositionSupervisorAgent:
    def __init__(self, broker: Broker, config: AppConfig) -> None:
        self.broker = broker
        self.config = config

    def supervise(self, halt_all: bool = False) -> None:
        for pos in self.broker.open_positions():
            if halt_all:
                self.broker.close_position(pos.ticket, "arret_journalier")
                continue
            self._enforce_max_age(pos)
            self._move_breakeven(pos)

    def _enforce_max_age(self, pos: Position) -> None:
        age_min = (self.broker.now() - pos.opened_at).total_seconds() / 60.0
        if age_min >= self.config.trading.max_position_minutes:
            log.info("Position #%d (%s) a %.0f min → fermeture (limite %d min).",
                     pos.ticket, pos.symbol, age_min,
                     self.config.trading.max_position_minutes)
            self.broker.close_position(pos.ticket, "timeout_30min")

    def _move_breakeven(self, pos: Position) -> None:
        if pos.breakeven_moved:
            return
        df = self.broker.candles(pos.symbol, "M1", 3)
        if df is None or df.empty:
            return
        price = float(df["close"].iloc[-1])
        one_r = abs(pos.entry_price - pos.sl)
        if one_r <= 0:
            return
        gain = (price - pos.entry_price) * pos.direction
        if gain >= one_r * self.config.trading.breakeven_at_r:
            result = self.broker.modify_sl(pos.ticket, pos.entry_price)
            if result.ok:
                pos.breakeven_moved = True
                log.info("Position #%d (%s) : SL déplacé au point d'entrée (+1R atteint).",
                         pos.ticket, pos.symbol)
