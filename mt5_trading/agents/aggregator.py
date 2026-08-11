"""SignalAggregatorAgent : transforme des idées brutes en signaux notés.

C'est ici que la confluence se joue — un pattern seul ne suffit jamais.
Grille de score (min_confluence_score dans la config pour déclencher) :

  + force cumulée des patterns (plafonnée à 3)
  + 1.0  si aligné avec la micro-tendance M15
  + 1.0  si aligné avec le biais journalier D1
  + 0.5  si aligné avec le biais mensuel MN1
  + 1.0  si le prix rebondit sur un support (achat) / une résistance (vente)
  + 1.0  si le prix est dans une zone SMC favorable (Order Block ou FVG)
  + 1.0  si bougie englobante clôturée en zone OTE Fibonacci (règle Kasper)
  - 1.5  si un niveau opposé est trop proche (le trade n'a pas la place de respirer)
"""

from __future__ import annotations

import logging

from ..analysis.smc import in_ote_zone, zone_confluence
from ..analysis.structure import nearest_level
from ..broker.base import Broker
from ..config import AppConfig
from .base import MarketBias, TradeIdea, TradeSignal

log = logging.getLogger(__name__)


class SignalAggregatorAgent:
    def __init__(self, broker: Broker, config: AppConfig) -> None:
        self.broker = broker
        self.config = config

    def evaluate(self, idea: TradeIdea, bias: MarketBias) -> TradeSignal | None:
        d = idea.direction
        price = idea.last_price
        reasons: list[str] = [f"patterns={[p.pattern for p in idea.patterns]}"]

        score = min(3.0, float(sum(p.strength for p in idea.patterns)))

        if bias.micro.direction == d:
            score += 1.0
            reasons.append(f"micro-tendance alignée ({bias.micro.label})")
        if bias.daily.direction == d:
            score += 1.0
            reasons.append(f"biais journalier aligné ({bias.daily.label})")
        if bias.monthly.direction == d:
            score += 0.5
            reasons.append("biais mensuel aligné")

        # Rebond sur niveau : un achat vaut plus près d'un support qui a déjà réagi.
        bounce_level = nearest_level(bias.levels, price, "support" if d > 0 else "resistance")
        if bounce_level and abs(price - bounce_level.price) <= idea.atr and bounce_level.touches >= 2:
            score += 1.0
            reasons.append(f"rebond sur {bounce_level.kind} {bounce_level.price:.5g} "
                           f"({bounce_level.touches} touches)")

        # Confluence SMC (méthode Kasper : Order Block / FVG dans le sens du trade).
        df = self.broker.candles(idea.symbol, self.config.trading.signal_timeframe, 100)
        if df is not None:
            zones = zone_confluence(df, d)
            if zones:
                score += 1.0
                reasons.append(f"zone SMC {zones[0].kind} [{zones[0].bottom:.5g}-{zones[0].top:.5g}]")
            if any(p.pattern.startswith("avalement") for p in idea.patterns) \
                    and in_ote_zone(df, d):
                score += 1.0
                reasons.append("englobante en zone OTE Fibonacci (0.62-0.86)")

        # Obstacle : niveau opposé collé au prix → pas la place d'aller au TP.
        obstacle = nearest_level(bias.levels, price, "resistance" if d > 0 else "support")
        min_room = idea.atr * self.config.risk.min_reward_risk
        if obstacle and abs(obstacle.price - price) < min_room:
            score -= 1.5
            reasons.append(f"obstacle {obstacle.kind} trop proche ({obstacle.price:.5g})")

        if score < self.config.trading.min_confluence_score:
            log.debug("%s : score %.1f < %.1f → pas de signal", idea.symbol, score,
                      self.config.trading.min_confluence_score)
            return None

        # SL structurel : sous le dernier creux/sommet, au minimum 0.8 ATR.
        sl_distance = max(0.8 * idea.atr, self._structural_stop(idea, bias))
        sl = price - d * sl_distance
        tp = price + d * sl_distance * self.config.risk.min_reward_risk

        signal = TradeSignal(
            symbol=idea.symbol, direction=d, score=round(score, 2),
            entry_hint=price, sl=sl, tp=tp, rationale="; ".join(reasons),
        )
        log.info("SIGNAL %s %s score=%.1f | %s", idea.symbol,
                 "ACHAT" if d > 0 else "VENTE", score, signal.rationale)
        return signal

    def _structural_stop(self, idea: TradeIdea, bias: MarketBias) -> float:
        """Distance jusqu'au niveau structurel derrière l'entrée (règle Kasper :
        le stop va derrière la mèche/le dernier creux, jamais « dans » le bruit)."""
        protective = nearest_level(bias.levels, idea.last_price,
                                   "support" if idea.direction > 0 else "resistance")
        if protective is None:
            return 0.0
        distance = abs(idea.last_price - protective.price) + 0.2 * idea.atr
        return min(distance, 2.0 * idea.atr)  # un SL de scalp reste serré
