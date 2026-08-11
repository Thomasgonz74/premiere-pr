"""ExecutionAgent : envoie les ordres approuvés au broker, sans état d'âme."""

from __future__ import annotations

import logging

from ..broker.base import Broker
from .base import SizedOrder

log = logging.getLogger(__name__)


class ExecutionAgent:
    def __init__(self, broker: Broker) -> None:
        self.broker = broker

    def execute(self, order: SizedOrder) -> bool:
        s = order.signal
        result = self.broker.market_order(
            symbol=s.symbol,
            direction=s.direction,
            volume=order.volume,
            sl=s.sl,
            tp=s.tp,
            comment=f"scalp s={s.score}",
        )
        if result.ok:
            log.info("ORDRE EXÉCUTÉ #%d : %s %s %.2f lots, risque %.2f, score %.1f",
                     result.ticket, s.symbol, "ACHAT" if s.direction > 0 else "VENTE",
                     order.volume, order.risk_amount, s.score)
        else:
            log.error("Échec d'exécution %s : %s", s.symbol, result.message)
        return result.ok
