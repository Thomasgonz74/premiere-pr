"""Orchestrateur : fait tourner le réseau d'agents en boucle.

À chaque tick :
  1. le superviseur gère les positions ouvertes (30 min max, breakeven) ;
  2. le scanner établit la watchlist active (session, spread, volatilité) ;
  3. pour chaque symbole actif : lecture de tendance + analyse des chandelles ;
  4. l'agrégateur note la confluence et produit d'éventuels signaux ;
  5. le gestionnaire de risque dimensionne ou met son veto ;
  6. l'exécuteur envoie les ordres retenus.
"""

from __future__ import annotations

import logging
import time

from .agents.aggregator import SignalAggregatorAgent
from .agents.chart_analyst import ChartAnalystAgent
from .agents.executor import ExecutionAgent
from .agents.risk_manager import RiskManagerAgent
from .agents.scanner import MarketScannerAgent
from .agents.supervisor import PositionSupervisorAgent
from .agents.trend_agent import TrendContextAgent
from .broker.base import Broker
from .broker.paper import PaperBroker
from .config import AppConfig

log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, broker: Broker, config: AppConfig | None = None) -> None:
        self.broker = broker
        self.config = config or AppConfig()
        self.scanner = MarketScannerAgent(broker, self.config)
        self.trend = TrendContextAgent(broker, self.config)
        self.analyst = ChartAnalystAgent(broker, self.config)
        self.aggregator = SignalAggregatorAgent(broker, self.config)
        self.risk = RiskManagerAgent(broker, self.config)
        self.executor = ExecutionAgent(broker)
        self.supervisor = PositionSupervisorAgent(broker, self.config)

    def tick(self) -> None:
        self.supervisor.supervise(halt_all=self.risk.halted)
        if self.risk.halted:
            return
        for spec in self.scanner.scan():
            bias = self.trend.read(spec.name)
            if bias is None:
                continue
            idea = self.analyst.analyse(spec.name)
            if idea is None:
                continue
            signal = self.aggregator.evaluate(idea, bias)
            if signal is None:
                continue
            order = self.risk.approve(signal)
            if order is None:
                continue
            self.executor.execute(order)

    def run_forever(self) -> None:
        log.info("Démarrage de la boucle (tick toutes les %d s). Ctrl+C pour arrêter.",
                 self.config.trading.loop_seconds)
        try:
            while True:
                self.tick()
                if isinstance(self.broker, PaperBroker):
                    # En simulation, le temps avance au rythme des ticks.
                    self.broker.advance(1)
                time.sleep(self.config.trading.loop_seconds
                           if not isinstance(self.broker, PaperBroker) else 0.05)
        except KeyboardInterrupt:
            log.info("Arrêt demandé. Positions encore ouvertes : %d",
                     len(self.broker.open_positions()))

    def run_simulation(self, minutes: int = 480) -> dict:
        """Fait tourner le système sur `minutes` de marché simulé (mode paper)."""
        assert isinstance(self.broker, PaperBroker), "run_simulation exige le PaperBroker"
        for _ in range(minutes):
            self.tick()
            self.broker.advance(1)
        # Bilan
        account = self.broker.account()
        trades = self.broker.closed_trades
        wins = [t for t in trades if t["pnl"] > 0]
        report = {
            "minutes_simulees": minutes,
            "trades_fermes": len(trades),
            "gagnants": len(wins),
            "taux_reussite_pct": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
            "pnl_total": round(sum(t["pnl"] for t in trades), 2),
            "equity_finale": round(account.equity, 2),
        }
        log.info("Bilan simulation : %s", report)
        return report
