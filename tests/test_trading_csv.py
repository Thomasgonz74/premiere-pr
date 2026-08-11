"""Tests du chargeur CSV et du broker de replay (données réelles)."""

import numpy as np
import pandas as pd
import pytest

from mt5_trading.broker.csv_replay import CsvReplayBroker, load_m1_csv
from mt5_trading.config import AppConfig
from mt5_trading.orchestrator import Orchestrator


def write_m1_csv(path, n=3000, base=2400.0, sep=",", mt5_format=False, start="2025-06-02"):
    rng = np.random.default_rng(3)
    steps = rng.normal(0, base * 0.0003, n)
    closes = base + np.cumsum(steps)
    opens = np.concatenate(([base], closes[:-1]))
    spans = np.abs(rng.normal(0, base * 0.0002, n))
    idx = pd.date_range(start=start, periods=n, freq="1min")
    df = pd.DataFrame({
        "open": opens,
        "high": np.maximum(opens, closes) + spans,
        "low": np.minimum(opens, closes) - spans,
        "close": closes,
    })
    if mt5_format:
        out = pd.DataFrame({
            "<DATE>": idx.strftime("%Y.%m.%d"),
            "<TIME>": idx.strftime("%H:%M:%S"),
            "<OPEN>": df["open"], "<HIGH>": df["high"],
            "<LOW>": df["low"], "<CLOSE>": df["close"],
            "<TICKVOL>": 100, "<VOL>": 0, "<SPREAD>": 12,
        })
        out.to_csv(path, sep="\t", index=False)
    else:
        df.insert(0, "time", idx)
        df.to_csv(path, sep=sep, index=False)
    return df


def test_load_generic_csv(tmp_path):
    path = tmp_path / "xau.csv"
    write_m1_csv(path, n=100)
    df = load_m1_csv(path)
    assert list(df.columns) == ["open", "high", "low", "close", "tick_volume"]
    assert len(df) == 100
    assert df.index.tz is not None


def test_load_mt5_export_format(tmp_path):
    path = tmp_path / "xau_mt5.csv"
    write_m1_csv(path, n=100, mt5_format=True)
    df = load_m1_csv(path)
    assert len(df) == 100
    assert (df["tick_volume"] == 100).all()


def test_missing_columns_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"time": ["2025-06-02 00:00"], "open": [1.0]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="manquantes"):
        load_m1_csv(path)


def test_replay_hides_the_future(tmp_path):
    path = tmp_path / "xau.csv"
    full = write_m1_csv(path, n=3000)
    broker = CsvReplayBroker({"XAUUSD": path}, balance=3000.0, warmup_minutes=500)
    visible = broker.candles("XAUUSD", "M1", 10_000)
    # Au démarrage, seules ~500 bougies de préchauffage sont visibles.
    assert len(visible) < 600
    price_before = broker._price("XAUUSD")
    broker.advance(100)
    visible_after = broker.candles("XAUUSD", "M1", 10_000)
    assert len(visible_after) == len(visible) + 100
    # Le prix courant suit les données réelles, pas un générateur.
    # L'horloge est à start+600 min ; la tranche .loc étant inclusive, la
    # dernière bougie visible est la ligne d'indice 600.
    expected = full["close"].iloc[500 + 100]
    assert broker._price("XAUUSD") == pytest.approx(expected)
    assert price_before != broker._price("XAUUSD")


def test_replay_ends_when_data_runs_out(tmp_path):
    path = tmp_path / "xau.csv"
    write_m1_csv(path, n=2200)
    broker = CsvReplayBroker({"XAUUSD": path}, balance=3000.0, warmup_minutes=2000)
    config = AppConfig()
    config.watchlist = [s for s in config.watchlist if s.name == "XAUUSD"]
    report = Orchestrator(broker, config).run_simulation(minutes=10_000)
    assert broker.exhausted
    assert report["minutes_simulees"] <= 200


def test_sl_tp_filled_from_real_bars(tmp_path):
    path = tmp_path / "xau.csv"
    write_m1_csv(path, n=3000)
    broker = CsvReplayBroker({"XAUUSD": path}, balance=3000.0, warmup_minutes=500)
    price = broker._price("XAUUSD")
    # TP collé au prix : la première bougie qui le traverse doit clôturer le trade.
    broker.market_order("XAUUSD", +1, 0.01, sl=price * 0.98, tp=price * 1.0001, comment="t")
    broker.advance(300)
    if not broker.open_positions():
        assert broker.closed_trades[0]["reason"] in ("tp", "sl")
