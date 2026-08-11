"""Connexion au terminal MetaTrader 5 (Windows uniquement).

Le paquet Python `MetaTrader5` pilote un terminal MT5 installé et connecté à
votre compte broker. Ce module est importable partout, mais `connect()` échoue
proprement si le paquet ou le terminal est absent.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from .base import AccountState, Broker, OrderResult, Position, SymbolInfo

log = logging.getLogger(__name__)

try:
    import MetaTrader5 as mt5
except ImportError:  # macOS/Linux ou paquet absent → mode paper uniquement
    mt5 = None

_TIMEFRAMES: dict[str, int] = {}
if mt5 is not None:
    _TIMEFRAMES = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
        "MN1": mt5.TIMEFRAME_MN1,
    }


class Mt5Client(Broker):
    def __init__(self) -> None:
        if mt5 is None:
            raise RuntimeError(
                "Le paquet MetaTrader5 n'est pas disponible (Windows requis). "
                "Utilisez --mode paper sur cette machine."
            )

    def connect(self, login: int | None = None, password: str | None = None,
                server: str | None = None) -> None:
        """Attache le terminal MT5 déjà ouvert (ou le lance). Sans identifiants,
        reprend le compte connecté dans le terminal."""
        kwargs = {}
        if login:
            kwargs = {"login": login, "password": password, "server": server}
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"mt5.initialize a échoué : {mt5.last_error()}")
        info = mt5.account_info()
        if info is None:
            raise RuntimeError("Aucun compte connecté dans le terminal MT5.")
        log.info("Connecté au compte %s (%s), levier 1:%s", info.login, info.server, info.leverage)

    def shutdown(self) -> None:
        mt5.shutdown()

    def account(self) -> AccountState:
        info = mt5.account_info()
        return AccountState(
            balance=info.balance,
            equity=info.equity,
            margin_used=info.margin,
            margin_free=info.margin_free,
            currency=info.currency,
        )

    def symbol_info(self, symbol: str) -> SymbolInfo | None:
        if not mt5.symbol_select(symbol, True):
            return None
        si = mt5.symbol_info(symbol)
        if si is None:
            return None
        margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, symbol, 1.0, si.ask) or 0.0
        return SymbolInfo(
            name=symbol,
            point=si.point,
            spread_points=float(si.spread),
            volume_min=si.volume_min,
            volume_step=si.volume_step,
            contract_size=si.trade_contract_size,
            tick_value=si.trade_tick_value,
            margin_per_lot=margin,
        )

    def candles(self, symbol: str, timeframe: str, count: int) -> pd.DataFrame | None:
        rates = mt5.copy_rates_from_pos(symbol, _TIMEFRAMES[timeframe], 0, count)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")[["open", "high", "low", "close", "tick_volume"]]
        # La dernière ligne est la bougie en cours (non clôturée) : on l'écarte
        # pour ne lire que des chandelles terminées.
        return df.iloc[:-1]

    def market_order(self, symbol: str, direction: int, volume: float,
                     sl: float, tp: float, comment: str) -> OrderResult:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return OrderResult(False, message="pas de cotation")
        price = tick.ask if direction > 0 else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY if direction > 0 else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 573001,
            "comment": comment[:26],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return OrderResult(False, message=f"retcode={getattr(result, 'retcode', '?')}")
        return OrderResult(True, ticket=result.order)

    def close_position(self, ticket: int, reason: str) -> OrderResult:
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return OrderResult(False, message="position introuvable")
        p = pos[0]
        tick = mt5.symbol_info_tick(p.symbol)
        is_long = p.type == mt5.POSITION_TYPE_BUY
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": mt5.ORDER_TYPE_SELL if is_long else mt5.ORDER_TYPE_BUY,
            "position": ticket,
            "price": tick.bid if is_long else tick.ask,
            "deviation": 20,
            "magic": 573001,
            "comment": reason[:26],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        return OrderResult(ok, message="" if ok else f"retcode={getattr(result, 'retcode', '?')}")

    def modify_sl(self, ticket: int, new_sl: float) -> OrderResult:
        pos = mt5.positions_get(ticket=ticket)
        if not pos:
            return OrderResult(False, message="position introuvable")
        p = pos[0]
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": p.symbol,
            "position": ticket,
            "sl": new_sl,
            "tp": p.tp,
        }
        result = mt5.order_send(request)
        ok = result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        return OrderResult(ok)

    def open_positions(self) -> list[Position]:
        raw = mt5.positions_get() or []
        out = []
        for p in raw:
            if p.magic != 573001:
                continue  # ne touche jamais aux positions ouvertes à la main
            out.append(Position(
                ticket=p.ticket,
                symbol=p.symbol,
                direction=+1 if p.type == mt5.POSITION_TYPE_BUY else -1,
                volume=p.volume,
                entry_price=p.price_open,
                sl=p.sl,
                tp=p.tp,
                opened_at=datetime.fromtimestamp(p.time, tz=timezone.utc),
                comment=p.comment,
            ))
        return out

    def now(self) -> datetime:
        return datetime.now(timezone.utc)
