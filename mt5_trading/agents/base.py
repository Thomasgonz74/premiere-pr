"""Types de messages échangés entre les agents du réseau.

Le flux d'une décision :
  Scanner → watchlist active
  TrendContextAgent → biais (journalier/mensuel) par symbole
  ChartAnalystAgent → idées de trade (patterns bruts)
  SignalAggregatorAgent → signaux notés par confluence, avec SL/TP
  RiskManagerAgent → ordres dimensionnés (ou veto)
  ExecutionAgent → ordres envoyés au broker
  PositionSupervisorAgent → gestion des positions (30 min max, breakeven)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..analysis.candles import CandleSignal
from ..analysis.structure import Level, TrendReading


@dataclass
class MarketBias:
    """Contexte multi-timeframe d'un symbole (lu par le TrendContextAgent)."""

    symbol: str
    micro: TrendReading      # M15
    daily: TrendReading      # D1
    monthly: TrendReading    # MN1
    levels: list[Level] = field(default_factory=list)


@dataclass
class TradeIdea:
    """Sortie brute d'un analyste graphique : des patterns, pas encore un trade."""

    symbol: str
    direction: int
    patterns: list[CandleSignal]
    last_price: float
    atr: float


@dataclass
class TradeSignal:
    """Idée validée par la confluence, prête pour le gestionnaire de risque."""

    symbol: str
    direction: int
    score: float
    entry_hint: float
    sl: float
    tp: float
    rationale: str


@dataclass
class SizedOrder:
    """Signal dimensionné et approuvé par le risque."""

    signal: TradeSignal
    volume: float
    risk_amount: float
