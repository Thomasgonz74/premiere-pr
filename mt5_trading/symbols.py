"""Résolution des noms de symboles côté broker.

Chaque broker nomme ses instruments à sa façon : XAUUSD, GOLD, XAUUSD.a,
EURUSD.p, USOIL… Au démarrage, on fait correspondre la watchlist canonique
aux symboles réellement proposés par le broker, pour ne jamais trader un
mauvais instrument ni échouer sur un suffixe.
"""

from __future__ import annotations

import dataclasses
import logging

from .broker.base import Broker
from .config import AppConfig, SymbolSpec

log = logging.getLogger(__name__)


def _match(candidates: tuple[str, ...], available_upper: dict[str, str]) -> str | None:
    # 1. Correspondance exacte (insensible à la casse).
    for cand in candidates:
        hit = available_upper.get(cand.upper())
        if hit is not None:
            return hit
    # 2. Correspondance par préfixe : EURUSD → EURUSD.a / EURUSD.p / EURUSDm.
    #    On prend le nom le plus court, le plus proche du canonique.
    for cand in candidates:
        prefix = cand.upper()
        hits = [orig for up, orig in available_upper.items() if up.startswith(prefix)]
        if hits:
            return min(hits, key=len)
    return None


def resolve_watchlist(broker: Broker, config: AppConfig) -> None:
    """Remplace en place les noms canoniques de la watchlist par les noms
    du broker. Les symboles introuvables sont retirés (avec avertissement)."""
    try:
        available = broker.list_symbols()
    except NotImplementedError:
        return
    if not available:
        log.warning("Le broker n'a renvoyé aucun symbole — watchlist inchangée.")
        return
    available_upper = {s.upper(): s for s in available}

    resolved: list[SymbolSpec] = []
    for spec in config.watchlist:
        name = _match((spec.name, *spec.aliases), available_upper)
        if name is None:
            log.warning("Symbole %s introuvable chez ce broker (alias essayés : %s) — retiré.",
                        spec.name, ", ".join(spec.aliases) or "aucun")
            continue
        if name != spec.name:
            log.info("Symbole %s résolu en « %s » chez ce broker.", spec.name, name)
            spec = dataclasses.replace(spec, name=name)
        resolved.append(spec)
    config.watchlist = resolved
