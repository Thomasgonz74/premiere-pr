"""RiskManagerAgent : le seul agent qui a le droit de dire non.

Avec un levier 1:1000, la marge n'est jamais la contrainte — le risque l'est.
Le dimensionnement part TOUJOURS de la distance du stop-loss, jamais de la
marge disponible. Vetos successifs :

  1. perte journalière max atteinte → système à l'arrêt jusqu'à demain ;
  2. nombre max de trades du jour atteint (anti-overtrading) ;
  3. trop de positions ouvertes ;
  4. déjà une position sur ce symbole ;
  5. volume calculé sous le minimum du broker → trade refusé (jamais surdimensionné) ;
  6. marge utilisée > plafond (5 % par défaut) même si le levier le permettrait.
"""

from __future__ import annotations

import logging
from datetime import date

from ..broker.base import Broker
from ..config import AppConfig
from .base import SizedOrder, TradeSignal

log = logging.getLogger(__name__)


class RiskManagerAgent:
    def __init__(self, broker: Broker, config: AppConfig) -> None:
        self.broker = broker
        self.config = config
        self._day: date | None = None
        self._day_start_equity = 0.0
        self._trades_today = 0
        self.halted = False

    def _roll_day(self) -> None:
        today = self.broker.now().date()
        if self._day != today:
            self._day = today
            self._day_start_equity = self.broker.account().equity
            self._trades_today = 0
            self.halted = False

    def daily_drawdown_pct(self) -> float:
        if self._day_start_equity <= 0:
            return 0.0
        equity = self.broker.account().equity
        return max(0.0, (self._day_start_equity - equity) / self._day_start_equity * 100)

    def approve(self, signal: TradeSignal) -> SizedOrder | None:
        self._roll_day()
        cfg = self.config.risk
        account = self.broker.account()

        dd = self.daily_drawdown_pct()
        if dd >= cfg.max_daily_loss_pct:
            if not self.halted:
                log.warning("ARRÊT JOURNALIER : perte de %.1f%% ≥ %.1f%%. "
                            "Plus aucun trade aujourd'hui.", dd, cfg.max_daily_loss_pct)
            self.halted = True
            return None
        if self._trades_today >= cfg.max_trades_per_day:
            log.info("Veto %s : quota de %d trades/jour atteint.", signal.symbol,
                     cfg.max_trades_per_day)
            return None

        positions = self.broker.open_positions()
        if len(positions) >= cfg.max_open_positions:
            log.info("Veto %s : %d positions déjà ouvertes.", signal.symbol, len(positions))
            return None
        if any(p.symbol == signal.symbol for p in positions):
            log.info("Veto %s : position déjà ouverte sur ce symbole.", signal.symbol)
            return None

        info = self.broker.symbol_info(signal.symbol)
        if info is None:
            return None

        # Dimensionnement par le risque : (capital x %risque) / (distance SL en devise/lot).
        risk_amount = account.equity * cfg.risk_per_trade_pct / 100.0
        sl_distance = abs(signal.entry_hint - signal.sl)
        loss_per_lot = sl_distance * info.contract_size
        if loss_per_lot <= 0:
            return None
        volume = risk_amount / loss_per_lot
        # Arrondi AU PAS INFÉRIEUR : on ne dépasse jamais le risque cible.
        volume = int(volume / info.volume_step) * info.volume_step
        if volume < info.volume_min:
            log.info("Veto %s : capital insuffisant pour risquer ≤ %.2f %s sur ce SL "
                     "(volume %.3f < min %.2f). On ne surdimensionne JAMAIS.",
                     signal.symbol, risk_amount, account.currency, volume, info.volume_min)
            return None

        # Garde-fou marge : même à levier 1000, on plafonne l'exposition.
        margin_needed = volume * info.margin_per_lot
        margin_cap = account.equity * self.config.risk.max_margin_usage_pct / 100.0
        if account.margin_used + margin_needed > margin_cap:
            log.info("Veto %s : marge %.2f dépasserait le plafond de %.1f%% de l'équité.",
                     signal.symbol, margin_needed, cfg.max_margin_usage_pct)
            return None

        self._trades_today += 1
        return SizedOrder(signal=signal, volume=round(volume, 2), risk_amount=risk_amount)
