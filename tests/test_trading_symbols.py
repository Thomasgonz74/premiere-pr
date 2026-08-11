"""Tests de la résolution des symboles broker et des profils de stratégie."""

import pytest

from mt5_trading.broker.paper import PaperBroker
from mt5_trading.config import AppConfig, make_config
from mt5_trading.symbols import resolve_watchlist


class FakeAxiBroker(PaperBroker):
    """Broker imitant un nommage AXI : suffixes et pétrole nommé USOIL."""

    def list_symbols(self) -> list[str]:
        return ["EURUSD.a", "GBPUSD.a", "USDJPY.a", "GBPJPY.a",
                "XAUUSD.a", "XAGUSD.a", "USOIL.a", "NAS100", "BTCUSD"]


def test_suffixed_symbols_resolved():
    config = AppConfig()
    resolve_watchlist(FakeAxiBroker(), config)
    names = {s.name for s in config.watchlist}
    assert "EURUSD.a" in names and "XAUUSD.a" in names


def test_oil_resolved_via_alias():
    config = AppConfig()
    resolve_watchlist(FakeAxiBroker(), config)
    assert any(s.name == "USOIL.a" for s in config.watchlist)


def test_unresolvable_symbol_removed():
    class TinyBroker(PaperBroker):
        def list_symbols(self):
            return ["EURUSD"]

    config = AppConfig()
    resolve_watchlist(TinyBroker(), config)
    assert [s.name for s in config.watchlist] == ["EURUSD"]


def test_exact_names_untouched():
    config = AppConfig()
    resolve_watchlist(PaperBroker(), config)  # PaperBroker utilise les noms canoniques
    assert any(s.name == "XAUUSD" for s in config.watchlist)
    assert len(config.watchlist) == 7


def test_profiles():
    assert make_config("standard").trading.min_confluence_score == 3.0
    assert make_config("selectif").trading.min_confluence_score == 4.0
    prudent = make_config("prudent")
    assert prudent.risk.risk_per_trade_pct == 0.25
    assert prudent.risk.max_open_positions == 1
    assert prudent.risk.max_trades_per_day == 5
    with pytest.raises(ValueError):
        make_config("yolo")
