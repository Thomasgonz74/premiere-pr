"""Broker papier : simulation locale pour tester le système sans MT5.

Génère des données synthétiques (marche aléatoire avec tendance et volatilité
par instrument) et exécute les ordres au prix de clôture courant. Utile pour
valider toute la chaîne d'agents avant de brancher un compte démo réel.
"""

from __future__ import annotations

import itertools
import logging
import random
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .base import AccountState, Broker, OrderResult, Position, SymbolInfo

log = logging.getLogger(__name__)

_TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440, "MN1": 43200}

_BASE_PRICES = {
    "XAUUSD": 2400.0, "XAGUSD": 29.0, "XTIUSD": 78.0,
    "EURUSD": 1.09, "GBPUSD": 1.28, "USDJPY": 155.0, "GBPJPY": 198.0,
}


class PaperBroker(Broker):
    def __init__(self, balance: float = 500.0, leverage: int = 1000, seed: int = 42) -> None:
        self._balance = balance
        self._leverage = leverage
        self._rng = random.Random(seed)
        self._np_rng = np.random.default_rng(seed)
        self._positions: dict[int, Position] = {}
        self._tickets = itertools.count(1)
        self._clock = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        self._series: dict[str, pd.DataFrame] = {}
        self.closed_trades: list[dict] = []

    # ------------------------------------------------------------------ marché
    def _ensure_series(self, symbol: str) -> pd.DataFrame:
        """Série M1 synthétique ; les autres timeframes sont ré-échantillonnés."""
        if symbol not in self._series:
            base = _BASE_PRICES.get(symbol, 100.0)
            n = 40_000  # ~1 mois de M1
            vol = base * 0.0004
            drift = self._np_rng.normal(0, vol * 0.02)
            steps = self._np_rng.normal(drift, vol, n)
            closes = base + np.cumsum(steps)
            opens = np.concatenate(([base], closes[:-1]))
            spans = np.abs(self._np_rng.normal(0, vol, n))
            highs = np.maximum(opens, closes) + spans
            lows = np.minimum(opens, closes) - spans
            idx = pd.date_range(end=self._clock, periods=n, freq="1min", tz="UTC")
            self._series[symbol] = pd.DataFrame(
                {"open": opens, "high": highs, "low": lows, "close": closes,
                 "tick_volume": self._np_rng.integers(50, 500, n)},
                index=idx,
            )
        return self._series[symbol]

    def advance(self, minutes: int = 1) -> None:
        """Fait avancer l'horloge simulée et prolonge les séries de prix."""
        self._clock += timedelta(minutes=minutes)
        for symbol, df in self._series.items():
            base_vol = float(_BASE_PRICES.get(symbol, 100.0)) * 0.0004
            last_close = float(df["close"].iloc[-1])
            rows = []
            idx = []
            t = df.index[-1]
            for _ in range(minutes):
                t = t + timedelta(minutes=1)
                o = last_close
                c = o + self._np_rng.normal(0, base_vol)
                span = abs(self._np_rng.normal(0, base_vol))
                rows.append({"open": o, "high": max(o, c) + span,
                             "low": min(o, c) - span, "close": c,
                             "tick_volume": int(self._np_rng.integers(50, 500))})
                last_close = c
                idx.append(t)
            self._series[symbol] = pd.concat([df, pd.DataFrame(rows, index=idx)])
        self._check_sl_tp()

    def _price(self, symbol: str) -> float:
        return float(self._ensure_series(symbol)["close"].iloc[-1])

    def _pip_value_per_lot(self, symbol: str) -> float:
        info = self.symbol_info(symbol)
        return info.contract_size * info.point

    def _check_sl_tp(self) -> None:
        for ticket, pos in list(self._positions.items()):
            df = self._ensure_series(pos.symbol)
            last = df.iloc[-1]
            if pos.direction > 0:
                if last["low"] <= pos.sl:
                    self._close_at(ticket, pos.sl, "sl")
                elif last["high"] >= pos.tp:
                    self._close_at(ticket, pos.tp, "tp")
            else:
                if last["high"] >= pos.sl:
                    self._close_at(ticket, pos.sl, "sl")
                elif last["low"] <= pos.tp:
                    self._close_at(ticket, pos.tp, "tp")

    def _close_at(self, ticket: int, price: float, reason: str) -> None:
        pos = self._positions.pop(ticket)
        info = self.symbol_info(pos.symbol)
        pnl = (price - pos.entry_price) * pos.direction * pos.volume * info.contract_size
        self._balance += pnl
        self.closed_trades.append({
            "symbol": pos.symbol, "direction": pos.direction, "volume": pos.volume,
            "entry": pos.entry_price, "exit": price, "pnl": round(pnl, 2),
            "reason": reason, "comment": pos.comment,
        })
        log.info("[PAPER] Fermeture %s %s @ %.5f (%s) pnl=%.2f",
                 pos.symbol, "LONG" if pos.direction > 0 else "SHORT", price, reason, pnl)

    # ------------------------------------------------------------------ Broker
    def list_symbols(self) -> list[str]:
        return list(_BASE_PRICES)

    def account(self) -> AccountState:
        equity = self._balance
        margin = 0.0
        for pos in self._positions.values():
            info = self.symbol_info(pos.symbol)
            price = self._price(pos.symbol)
            equity += (price - pos.entry_price) * pos.direction * pos.volume * info.contract_size
            margin += pos.volume * info.margin_per_lot
        return AccountState(self._balance, equity, margin, equity - margin)

    def symbol_info(self, symbol: str) -> SymbolInfo | None:
        base = _BASE_PRICES.get(symbol)
        if base is None:
            return None
        point = 0.01 if base > 50 else (0.001 if base > 5 else 0.00001)
        contract = 100.0 if symbol.startswith(("XAU", "XTI")) else (
            1000.0 if symbol.startswith("XAG") else 100_000.0)
        price = self._price(symbol)
        return SymbolInfo(
            name=symbol,
            point=point,
            spread_points=float(self._rng.uniform(5, 20)),
            volume_min=0.01,
            volume_step=0.01,
            contract_size=contract,
            tick_value=contract * point,
            margin_per_lot=contract * price / self._leverage,
        )

    def candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame | None:
        df = self._ensure_series(symbol)
        minutes = _TF_MINUTES[timeframe]
        if minutes > 1:
            df = df.resample(f"{minutes}min").agg(
                {"open": "first", "high": "max", "low": "min",
                 "close": "last", "tick_volume": "sum"}).dropna()
        return df.iloc[:-1].tail(count)  # bougie en cours écartée, comme en réel

    def market_order(self, symbol: str, direction: int, volume: float,
                     sl: float, tp: float, comment: str) -> OrderResult:
        price = self._price(symbol)
        ticket = next(self._tickets)
        self._positions[ticket] = Position(
            ticket=ticket, symbol=symbol, direction=direction, volume=volume,
            entry_price=price, sl=sl, tp=tp, opened_at=self._clock, comment=comment,
        )
        log.info("[PAPER] Ouverture #%d %s %s %.2f lots @ %.5f SL=%.5f TP=%.5f (%s)",
                 ticket, symbol, "LONG" if direction > 0 else "SHORT",
                 volume, price, sl, tp, comment)
        return OrderResult(True, ticket=ticket)

    def close_position(self, ticket: int, reason: str) -> OrderResult:
        if ticket not in self._positions:
            return OrderResult(False, message="position introuvable")
        self._close_at(ticket, self._price(self._positions[ticket].symbol), reason)
        return OrderResult(True)

    def modify_sl(self, ticket: int, new_sl: float) -> OrderResult:
        pos = self._positions.get(ticket)
        if pos is None:
            return OrderResult(False, message="position introuvable")
        pos.sl = new_sl
        return OrderResult(True)

    def open_positions(self) -> list[Position]:
        return list(self._positions.values())

    def now(self) -> datetime:
        return self._clock
