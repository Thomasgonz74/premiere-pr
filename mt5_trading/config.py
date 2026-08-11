"""Configuration centrale du système de trading multi-agents.

Toutes les valeurs par défaut sont volontairement conservatrices : un levier
1:1000 est un outil de marge, pas une invitation à l'utiliser en entier.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SymbolSpec:
    """Instrument surveillé et ses métadonnées."""

    name: str            # nom canonique (résolu automatiquement côté broker)
    kind: str            # "commodity" ou "forex"
    description: str
    priority: int        # 1 = cœur de la watchlist, 2 = secondaire
    max_spread_points: float  # spread max toléré (en points) pour scalper
    aliases: tuple[str, ...] = ()  # noms alternatifs selon les brokers


# Watchlist : matières premières + forex, choisie pour la liquidité et la
# volatilité intra-journalière (conditions nécessaires au scalping < 30 min).
WATCHLIST: list[SymbolSpec] = [
    SymbolSpec("XAUUSD", "commodity", "Or — le roi du scalping, volatil et liquide", 1, 35.0,
               aliases=("GOLD",)),
    SymbolSpec("XAGUSD", "commodity", "Argent — volatil, spreads plus larges", 2, 45.0,
               aliases=("SILVER",)),
    SymbolSpec("XTIUSD", "commodity", "Pétrole WTI — fort en session US", 2, 60.0,
               aliases=("USOIL", "WTI", "CL-OIL", "CRUDEOIL", "OILUS")),
    SymbolSpec("EURUSD", "forex", "Paire la plus liquide, spread minimal", 1, 12.0),
    SymbolSpec("GBPUSD", "forex", "Volatile en session Londres", 1, 15.0),
    SymbolSpec("USDJPY", "forex", "Liquide, propre techniquement", 2, 15.0),
    SymbolSpec("GBPJPY", "forex", "Très volatile — réservée aux meilleurs setups", 2, 25.0),
]


@dataclass(frozen=True)
class RiskConfig:
    """Garde-fous non négociables du gestionnaire de risque."""

    account_leverage: int = 1000
    risk_per_trade_pct: float = 0.5      # % du capital risqué par trade
    max_daily_loss_pct: float = 3.0      # perte journalière max → arrêt du système
    max_open_positions: int = 2          # positions simultanées max
    max_margin_usage_pct: float = 5.0    # marge utilisée max (malgré le levier 1000)
    min_reward_risk: float = 1.5         # ratio TP/SL minimal accepté
    max_trades_per_day: int = 30         # anti-overtrading


@dataclass(frozen=True)
class TradingConfig:
    """Paramètres de la boucle de trading."""

    signal_timeframe: str = "M5"         # lecture des chandelles / patterns
    context_timeframe: str = "M15"       # micro-tendance
    daily_timeframe: str = "D1"          # biais journalier
    monthly_timeframe: str = "MN1"       # biais de fond
    max_position_minutes: int = 30       # durée max d'une position (exigence)
    breakeven_at_r: float = 1.0          # SL au point d'entrée à +1R
    loop_seconds: int = 15               # cadence de la boucle principale
    min_confluence_score: float = 3.0    # score minimal pour déclencher un trade
    # Sessions actives (UTC) : Londres + New York, là où le scalping respire.
    sessions_utc: tuple[tuple[int, int], ...] = ((7, 11), (12, 17))


@dataclass
class AppConfig:
    risk: RiskConfig = field(default_factory=RiskConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    watchlist: list[SymbolSpec] = field(default_factory=lambda: list(WATCHLIST))

    def core_symbols(self) -> list[SymbolSpec]:
        return [s for s in self.watchlist if s.priority == 1]


# Profils de stratégie prêts à tester (comparaison A/B en session).
PROFILES: dict[str, str] = {
    "standard": "score min 3.0, 30 trades/jour, risque 0.5 %/trade",
    "selectif": "score min 4.0 — ne prend que les meilleures confluences",
    "prudent": "score min 4.0, 5 trades/jour, 1 position, risque 0.25 %/trade "
               "— recommandé pour les premières sessions réelles",
}


def make_config(profile: str = "standard") -> AppConfig:
    if profile == "standard":
        return AppConfig()
    if profile == "selectif":
        return AppConfig(trading=TradingConfig(min_confluence_score=4.0))
    if profile == "prudent":
        return AppConfig(
            risk=RiskConfig(risk_per_trade_pct=0.25, max_trades_per_day=5,
                            max_open_positions=1),
            trading=TradingConfig(min_confluence_score=4.0),
        )
    raise ValueError(f"Profil inconnu : {profile} (choix : {', '.join(PROFILES)})")
