"""Point d'entrée du système de trading multi-agents.

Modes :
  paper (défaut) : simulation locale, aucune dépendance MT5 — pour valider la
                   chaîne complète d'agents sans risquer un centime.
  live           : compte réel ou démo via le terminal MetaTrader 5 (Windows).
                   COMMENCEZ TOUJOURS PAR UN COMPTE DÉMO.

Exemples :
  python -m mt5_trading.main                          # simulation de 8 h
  python -m mt5_trading.main --mode paper --minutes 960
  python -m mt5_trading.main --mode live              # terminal MT5 déjà connecté
  python -m mt5_trading.main --mode live --login 123456 --server Broker-Demo
"""

from __future__ import annotations

import argparse
import getpass
import logging

from .config import AppConfig
from .orchestrator import Orchestrator

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scalping multi-agents MT5")
    parser.add_argument("--mode", choices=["paper", "csv", "live"], default="paper")
    parser.add_argument("--minutes", type=int, default=480,
                        help="durée de la simulation en minutes de marché "
                             "(mode csv : 0 = tout l'historique disponible)")
    parser.add_argument("--balance", type=float, default=500.0,
                        help="capital de départ simulé (modes paper et csv)")
    parser.add_argument("--data", action="append", default=[],
                        metavar="SYMBOLE=FICHIER.csv",
                        help="mode csv : données M1 réelles, répétable "
                             "(ex. --data XAUUSD=xauusd_m1.csv --data EURUSD=eu.csv)")
    parser.add_argument("--login", type=int, default=None, help="login MT5 (mode live)")
    parser.add_argument("--server", type=str, default=None, help="serveur broker (mode live)")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    config = AppConfig()

    if args.mode == "paper":
        from .broker.paper import PaperBroker
        broker = PaperBroker(balance=args.balance, leverage=config.risk.account_leverage)
        orchestrator = Orchestrator(broker, config)
        report = orchestrator.run_simulation(minutes=args.minutes)
        print("\n=== Bilan de la simulation (prix synthétiques) ===")
        for key, value in report.items():
            print(f"  {key}: {value}")
    elif args.mode == "csv":
        from .broker.csv_replay import CsvReplayBroker
        data_files = {}
        for item in args.data:
            symbol, _, path = item.partition("=")
            if not path:
                raise SystemExit(f"--data mal formé : « {item} » (attendu SYMBOLE=FICHIER.csv)")
            data_files[symbol.upper()] = path
        if not data_files:
            raise SystemExit("Le mode csv exige au moins un --data SYMBOLE=FICHIER.csv")
        broker = CsvReplayBroker(data_files, balance=args.balance,
                                 leverage=config.risk.account_leverage)
        # Seuls les symboles fournis sont surveillés.
        config.watchlist = [s for s in config.watchlist if s.name in data_files]
        unknown = set(data_files) - {s.name for s in config.watchlist}
        if unknown:
            log.warning("Symboles hors watchlist (ajoutez-les dans config.py) : %s",
                        ", ".join(sorted(unknown)))
        minutes = args.minutes or broker.replayable_minutes()
        report = Orchestrator(broker, config).run_simulation(minutes=minutes)
        print("\n=== Bilan du backtest (données réelles) ===")
        for key, value in report.items():
            print(f"  {key}: {value}")
        if broker.closed_trades:
            print("\n  Détail des trades :")
            for i, t in enumerate(broker.closed_trades, 1):
                sens = "ACHAT" if t["direction"] > 0 else "VENTE"
                print(f"  {i:>3} {t['symbol']:8} {sens:5} {t['volume']:.2f} lots "
                      f"entrée {t['entry']:.5g} → sortie {t['exit']:.5g} "
                      f"pnl {t['pnl']:+.2f} ({t['reason']})")
    else:
        from .broker.mt5_client import Mt5Client
        broker = Mt5Client()
        password = getpass.getpass("Mot de passe MT5 (vide si terminal déjà connecté) : ") \
            if args.login else None
        broker.connect(login=args.login, password=password, server=args.server)
        try:
            Orchestrator(broker, config).run_forever()
        finally:
            broker.shutdown()


if __name__ == "__main__":
    main()
