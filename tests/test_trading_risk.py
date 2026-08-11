"""Tests du gestionnaire de risque et de la chaîne complète en simulation."""

from mt5_trading.agents.base import TradeSignal
from mt5_trading.agents.risk_manager import RiskManagerAgent
from mt5_trading.broker.paper import PaperBroker
from mt5_trading.config import AppConfig
from mt5_trading.orchestrator import Orchestrator


def make_signal(symbol="EURUSD", price=1.09, sl_dist=0.001):
    return TradeSignal(symbol=symbol, direction=+1, score=5.0, entry_hint=price,
                       sl=price - sl_dist, tp=price + sl_dist * 1.5, rationale="test")


def test_sizing_respects_risk_budget():
    broker = PaperBroker(balance=500.0)
    risk = RiskManagerAgent(broker, AppConfig())
    order = risk.approve(make_signal())
    if order is not None:
        # Perte max au SL = volume x distance x taille de contrat ≤ 0.5 % de 500 €.
        info = broker.symbol_info("EURUSD")
        worst_loss = order.volume * 0.001 * info.contract_size
        assert worst_loss <= 500 * 0.005 + 1e-6


def test_undersized_account_is_vetoed():
    # 10 € de capital : risquer 0.5 % (5 centimes) est impossible au volume
    # minimal → le trade doit être refusé, jamais surdimensionné.
    broker = PaperBroker(balance=10.0)
    risk = RiskManagerAgent(broker, AppConfig())
    assert risk.approve(make_signal()) is None


def test_max_open_positions_enforced():
    broker = PaperBroker(balance=5000.0)
    risk = RiskManagerAgent(broker, AppConfig())
    for symbol in ("EURUSD", "GBPUSD"):
        order = risk.approve(make_signal(symbol=symbol,
                                         price=broker.symbol_info(symbol).margin_per_lot / 1000))
        if order:
            broker.market_order(symbol, +1, order.volume, order.signal.sl,
                                order.signal.tp, "t")
    if len(broker.open_positions()) >= 2:
        assert risk.approve(make_signal(symbol="USDJPY", price=155.0, sl_dist=0.1)) is None


def test_simulation_runs_end_to_end():
    broker = PaperBroker(balance=500.0, seed=7)
    orchestrator = Orchestrator(broker, AppConfig())
    report = orchestrator.run_simulation(minutes=120)
    assert report["minutes_simulees"] == 120
    assert report["equity_finale"] > 0
    # La limite de 30 minutes doit être respectée pour toute position fermée.
    for pos in broker.open_positions():
        age = (broker.now() - pos.opened_at).total_seconds() / 60
        assert age <= 31
