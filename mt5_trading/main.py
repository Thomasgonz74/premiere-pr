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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scalping multi-agents MT5")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper")
    parser.add_argument("--minutes", type=int, default=480,
                        help="durée de la simulation en mode paper (minutes de marché)")
    parser.add_argument("--balance", type=float, default=500.0,
                        help="capital de départ simulé en mode paper")
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
        print("\n=== Bilan de la simulation ===")
        for key, value in report.items():
            print(f"  {key}: {value}")
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
