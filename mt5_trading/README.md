# Scalping multi-agents pour MetaTrader 5

Système de trading automatisé en réseau d'agents, basé **uniquement sur la
lecture de graphique** : chandelles japonaises, structure de marché
(supports/résistances, tendances journalières et mensuelles) et concepts
« Smart Money » (Order Blocks, Fair Value Gaps, zone OTE Fibonacci) inspirés
de la méthode publique documentée de Kasper Trading (tradingkasper.com).

Positions de **30 minutes maximum**, sessions de **Londres et New York**
uniquement.

## ⚠️ Avertissement — à lire avant tout

- **Le trading à effet de levier peut détruire votre capital en quelques
  minutes.** Un levier 1:1000 amplifie les pertes exactement comme les gains.
  Ce système plafonne volontairement la marge utilisée à ~5 % de l'équité :
  le levier sert à réduire la marge immobilisée, **jamais** à grossir les
  positions.
- **Aucune stratégie, celle-ci comprise, ne garantit de gains.** Les patterns
  de chandelles ont un pouvoir prédictif faible et instable ; les statistiques
  publiques des brokers CFD montrent que 70–85 % des comptes particuliers
  perdent de l'argent.
- **Commencez en mode `paper`, puis sur un COMPTE DÉMO pendant plusieurs
  semaines.** Ne passez en réel que si les résultats démo sont stables, et
  uniquement avec de l'argent dont la perte totale ne changerait rien à votre
  vie.
- Ce code est fourni à des fins éducatives. Vous restez seul responsable des
  ordres passés sur votre compte.

## Architecture : le réseau d'agents

```
                        ┌────────────────────┐
                        │  MarketScanner     │  session ? spread ? volatilité ?
                        └─────────┬──────────┘
                 watchlist active │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
     ┌────────────────┐  ┌────────────────┐  (un couple d'agents
     │ TrendContext   │  │ ChartAnalyst   │   par symbole actif)
     │ MN1/D1/M15 +   │  │ chandelles M5  │
     │ niveaux S/R    │  │ (8 détecteurs) │
     └───────┬────────┘  └───────┬────────┘
             │ biais             │ idées
             └────────┬──────────┘
                      ▼
           ┌─────────────────────┐
           │ SignalAggregator    │  score de confluence (patterns + tendances
           │                     │  + S/R + zones SMC + OTE Fibonacci)
           └─────────┬───────────┘
                     │ signaux (SL/TP structurels, RR ≥ 1.5)
                     ▼
           ┌─────────────────────┐
           │ RiskManager         │  0.5 %/trade, 3 %/jour max, 2 positions max,
           │ (droit de veto)     │  10 trades/jour, marge ≤ 5 % de l'équité
           └─────────┬───────────┘
                     │ ordres dimensionnés
                     ▼
           ┌─────────────────────┐      ┌──────────────────────┐
           │ ExecutionAgent      │      │ PositionSupervisor   │
           │ ordres marché+SL+TP │      │ 30 min max, breakeven │
           └─────────────────────┘      │ à +1R, arrêt d'urgence│
                                        └──────────────────────┘
```

## Instruments surveillés

| Symbole | Type | Rôle | Pourquoi |
|---|---|---|---|
| **XAUUSD** (or) | Matière première | Cœur | L'instrument de scalping de référence : volatil, liquide, techniquement propre. C'est aussi le marché principal de la méthode Kasper. |
| **EURUSD** | Forex | Cœur | Paire la plus liquide au monde, spread minimal. |
| **GBPUSD** | Forex | Cœur | Très active en session de Londres. |
| XAGUSD (argent) | Matière première | Secondaire | Volatil mais spreads plus larges — setups triés. |
| XTIUSD (pétrole WTI) | Matière première | Secondaire | Fort en session US. |
| USDJPY | Forex | Secondaire | Liquide, propre techniquement. |
| GBPJPY | Forex | Secondaire | Très volatile — réservée aux meilleurs scores. |

> Les noms de symboles varient selon les brokers (XAUUSD vs GOLD vs XAU/USD…).
> Adaptez `config.py` à votre broker.

## Capital de départ recommandé

Avec un levier 1:1000, la marge n'est jamais le facteur limitant — c'est la
**granularité du risque** qui dicte le capital minimal. Le système risque
0,5 % du capital par trade et refuse tout trade qu'il ne peut pas dimensionner
au volume minimal (0.01 lot) sans dépasser ce budget :

| Capital | Risque/trade (0,5 %) | Verdict |
|---|---|---|
| < 200 € | < 1 € | ❌ Impossible de placer des stops corrects en 0.01 lot sur l'or — le RiskManager refusera presque tout. |
| **300–500 €** | 1,50–2,50 € | ✅ **Minimum viable** : stops structurels possibles sur forex et or en 0.01 lot. |
| **1 000 €** | 5 € | ✅ Confortable : diversification sur 2 positions, stops respirants. |
| 2 000 €+ | 10 €+ | ✅ Le système exploite toute la watchlist sans contrainte. |

**Recommandation : 500 € pour démarrer** (après validation sur démo), avec la
perte journalière max de 3 % (15 €) qui coupe le système pour la journée.
N'ajoutez jamais de fonds pour « se refaire ».

## Stratégie (lecture de graphique pure)

1. **Contexte top-down** : biais mensuel (MN1) et journalier (D1) par la
   structure (sommets/creux ascendants ou descendants), micro-tendance M15
   pour le timing — jamais d'indicateur.
2. **Signal M5** : 8 détecteurs de chandelles — avalement (haussier/baissier),
   trois soldats/corbeaux, marteau, étoile filante, marubozu, pin bar,
   inside bar + cassure, doji de sommet/creux.
3. **Confluence** (inspirée de la méthode Kasper documentée) : le signal ne
   devient un trade que si le score atteint 3,0 — alignement des tendances,
   rebond sur un niveau ayant déjà réagi, présence dans un Order Block ou un
   FVG dans le sens du trade, bougie englobante clôturée en zone OTE
   Fibonacci (retracement 0,62–0,86).
4. **Sortie** : SL structurel (derrière le dernier creux/sommet, min 0,8 ATR),
   TP à 1,5 R minimum, breakeven à +1R, **fermeture forcée à 30 minutes**.
5. **Sessions** : Londres (7h–11h UTC) et New York (12h–17h UTC) uniquement —
   là où la liquidité rend le scalping possible.

## Installation et lancement

```bash
pip install -r mt5_trading/requirements.txt

# 1. Simulation locale (aucun compte requis, fonctionne partout)
python -m mt5_trading.main --mode paper --minutes 480 --balance 500

# 2. Compte DÉMO puis réel (Windows + terminal MT5 installé et connecté)
python -m mt5_trading.main --mode live
python -m mt5_trading.main --mode live --login 123456 --server MonBroker-Demo

# Tests
python -m pytest tests/test_trading_analysis.py tests/test_trading_risk.py
```

Le mode `live` ne touche **que** les positions ouvertes par le système
(magic number dédié) — vos positions manuelles sont ignorées.

## Limites connues

- Le mode `paper` utilise des prix synthétiques : il valide la mécanique des
  agents, **pas** la rentabilité de la stratégie. Pour un vrai backtest,
  branchez des données historiques réelles.
- Pas de filtre de calendrier économique : coupez le système manuellement
  autour des annonces majeures (NFP, CPI, décisions de la Fed), ou pendant
  les 30 minutes qui les suivent si vous ne voulez pas de la volatilité.
- L'analyse de contenu vidéo (YouTube/Telegram) n'est pas automatisable ici :
  la partie « méthode Kasper » repose sur ses articles publics documentés.
