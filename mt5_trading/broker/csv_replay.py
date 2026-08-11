"""Replay de données M1 réelles depuis des fichiers CSV.

Permet de backtester la chaîne complète d'agents sur de vrais prix, sans
aucun regard vers le futur : à chaque instant, les agents ne voient que les
bougies antérieures à l'horloge de simulation.

Formats acceptés (détection automatique) :
  - Export MetaTrader 5 (Affichage → Symboles → Barres → Exporter) :
    colonnes <DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>...
  - CSV générique avec colonnes time (ou date+time), open, high, low, close.

Attention aux fuseaux : les horodatages sont pris tels quels et supposés
UTC pour le filtre de sessions. Si vos données sont en heure serveur broker
(souvent UTC+2/3), ajustez `sessions_utc` dans config.py en conséquence.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import pandas as pd

from .base import SymbolInfo
from .paper import PaperBroker

log = logging.getLogger(__name__)


def load_m1_csv(path: str | Path) -> pd.DataFrame:
    """Charge un CSV de bougies M1 en DataFrame OHLC indexé par datetime UTC."""
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [str(c).strip().strip("<>").lower() for c in df.columns]

    if "date" in df.columns and "time" in df.columns:
        stamp = pd.to_datetime(
            df["date"].astype(str) + " " + df["time"].astype(str), utc=True
        )
    elif "time" in df.columns:
        stamp = pd.to_datetime(df["time"], utc=True)
    elif "datetime" in df.columns:
        stamp = pd.to_datetime(df["datetime"], utc=True)
    else:
        raise ValueError(f"{path} : aucune colonne temporelle trouvée "
                         "(attendu 'date'+'time', 'time' ou 'datetime').")

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} : colonnes manquantes {sorted(missing)}.")

    volume_col = next((c for c in ("tickvol", "tick_volume", "volume", "vol")
                       if c in df.columns), None)
    out = pd.DataFrame({
        "open": pd.to_numeric(df["open"]),
        "high": pd.to_numeric(df["high"]),
        "low": pd.to_numeric(df["low"]),
        "close": pd.to_numeric(df["close"]),
        "tick_volume": pd.to_numeric(df[volume_col]) if volume_col else 0,
    })
    out.index = stamp
    out = out[~out.index.duplicated(keep="last")].sort_index()
    if out.empty:
        raise ValueError(f"{path} : aucune bougie exploitable.")
    return out


class CsvReplayBroker(PaperBroker):
    """PaperBroker rejouant de vraies données M1 au lieu de prix synthétiques."""

    def __init__(self, data_files: dict[str, str | Path], balance: float = 500.0,
                 leverage: int = 1000, warmup_minutes: int = 1800) -> None:
        super().__init__(balance=balance, leverage=leverage)
        if not data_files:
            raise ValueError("Fournissez au moins un fichier : {'XAUUSD': 'xauusd_m1.csv'}")
        self._full: dict[str, pd.DataFrame] = {
            symbol: load_m1_csv(path) for symbol, path in data_files.items()
        }
        starts = [df.index[0] for df in self._full.values()]
        ends = [df.index[-1] for df in self._full.values()]
        self._end = min(ends)
        # L'horloge démarre après un préchauffage pour que les agents aient
        # de l'historique (structure M15, niveaux) dès le premier tick.
        self._clock = max(starts) + timedelta(minutes=warmup_minutes)
        if self._clock >= self._end:
            raise ValueError(
                f"Données trop courtes : il faut au moins {warmup_minutes} minutes "
                f"de préchauffage plus une période de test."
            )
        self.exhausted = False
        for symbol, df in self._full.items():
            log.info("Replay %s : %d bougies M1, du %s au %s", symbol, len(df),
                     df.index[0], df.index[-1])

    def replayable_minutes(self) -> int:
        """Minutes de marché disponibles entre l'horloge actuelle et la fin."""
        return max(0, int((self._end - self._clock).total_seconds() // 60))

    # --- surcharges : la seule source de prix est le fichier, borné à l'horloge
    def _ensure_series(self, symbol: str) -> pd.DataFrame:
        full = self._full.get(symbol)
        if full is None:
            raise KeyError(f"Pas de données CSV pour {symbol}")
        return full.loc[: self._clock]

    def advance(self, minutes: int = 1) -> None:
        for _ in range(minutes):
            if self._clock >= self._end:
                self.exhausted = True
                return
            self._clock += timedelta(minutes=1)
            self._check_sl_tp()

    def symbol_info(self, symbol: str) -> SymbolInfo | None:
        if symbol not in self._full:
            return None
        price = self._price(symbol)
        point = 0.01 if price > 50 else (0.001 if price > 5 else 0.00001)
        if symbol.upper().startswith(("XAU", "XTI", "XBR", "USOIL", "UKOIL")):
            contract = 100.0
        elif symbol.upper().startswith("XAG"):
            contract = 1000.0
        elif price < 500:  # paires forex classiques (y compris JPY)
            contract = 100_000.0
        else:
            contract = 1.0  # indices/crypto : 1 lot = 1 unité, à adapter
        return SymbolInfo(
            name=symbol,
            point=point,
            spread_points=10.0,  # spread forfaitaire : le CSV n'en contient pas
            volume_min=0.01,
            volume_step=0.01,
            contract_size=contract,
            tick_value=contract * point,
            margin_per_lot=contract * price / self._leverage,
        )
