"""Interface broker : ce dont les agents ont besoin, rien de plus.

Deux implémentations : Mt5Client (compte réel/démo via le terminal MetaTrader 5,
Windows) et PaperBroker (simulation locale, aucune dépendance).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd


@dataclass
class Position:
    ticket: int
    symbol: str
    direction: int          # +1 long, -1 short
    volume: float           # lots
    entry_price: float
    sl: float
    tp: float
    opened_at: datetime
    breakeven_moved: bool = False
    comment: str = ""


@dataclass
class AccountState:
    balance: float
    equity: float
    margin_used: float
    margin_free: float
    currency: str = "EUR"


@dataclass
class SymbolInfo:
    name: str
    point: float            # taille d'un point
    spread_points: float
    volume_min: float
    volume_step: float
    contract_size: float
    tick_value: float       # valeur d'un tick pour 1 lot, en devise du compte
    margin_per_lot: float   # marge requise pour 1 lot (levier inclus)


@dataclass
class OrderResult:
    ok: bool
    ticket: int = 0
    message: str = ""


class Broker(abc.ABC):
    """Contrat minimal entre les agents et le marché."""

    def list_symbols(self) -> list[str]:
        """Noms de tous les instruments proposés par le broker."""
        raise NotImplementedError

    @abc.abstractmethod
    def account(self) -> AccountState: ...

    @abc.abstractmethod
    def symbol_info(self, symbol: str) -> SymbolInfo | None: ...

    @abc.abstractmethod
    def candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame | None:
        """DataFrame OHLC indexé par datetime (colonnes open/high/low/close)."""

    @abc.abstractmethod
    def market_order(
        self, symbol: str, direction: int, volume: float, sl: float, tp: float, comment: str
    ) -> OrderResult: ...

    @abc.abstractmethod
    def close_position(self, ticket: int, reason: str) -> OrderResult: ...

    @abc.abstractmethod
    def modify_sl(self, ticket: int, new_sl: float) -> OrderResult: ...

    @abc.abstractmethod
    def open_positions(self) -> list[Position]: ...

    @abc.abstractmethod
    def now(self) -> datetime: ...
