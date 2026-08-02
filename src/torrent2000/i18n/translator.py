"""Lightweight, dependency-free i18n: a flat key -> translated-string
catalog per language, loaded from resources/i18n/{code}.json. French (fr)
is both the default language and the source of truth -- every key in the
app exists in fr.json first, and any language missing a key (a string
added after that language's catalog was last regenerated) falls back to
the French text rather than crashing or showing a raw key to the user.

Widgets don't re-render themselves when the language changes -- Qt has no
such magic for a plain .setText() call -- so every tab/dialog that uses
tr() also implements retranslate_ui(), re-applying tr() to its own
widgets, and MainWindow cascades a call to every tab's retranslate_ui()
whenever ProfileTab's language_changed signal fires.
"""

import json
from typing import Optional

from torrent2000.utils.resource_path import resource_path

DEFAULT_LANGUAGE = "fr"

LANGUAGE_LABELS: list[tuple[str, str]] = [
    ("Français", "fr"),
    ("English", "en"),
    ("Español", "es"),
    ("Deutsch", "de"),
    ("Português", "pt"),
    ("Italiano", "it"),
    ("中文", "zh"),
    ("日本語", "ja"),
    ("한국어", "ko"),
    ("Polski", "pl"),
    ("Русский", "ru"),
]

_VALID_LANGUAGE_CODES = {code for _, code in LANGUAGE_LABELS}

_catalogs: dict[str, dict[str, str]] = {}
_current_language = DEFAULT_LANGUAGE


def _load_catalog(code: str) -> dict[str, str]:
    if code not in _catalogs:
        path = resource_path("resources/i18n") / f"{code}.json"
        try:
            _catalogs[code] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _catalogs[code] = {}
    return _catalogs[code]


def set_language(code: Optional[str]) -> None:
    global _current_language
    _current_language = code if code in _VALID_LANGUAGE_CODES else DEFAULT_LANGUAGE
    _load_catalog(_current_language)


def current_language() -> str:
    return _current_language


def tr(key: str, **kwargs) -> str:
    """Look up `key` in the active language's catalog, falling back to
    French and then to the key itself, so a missing/mistyped key degrades
    to visible-but-harmless text instead of raising. kwargs are applied
    via str.format for the handful of strings with dynamic content (counts,
    filenames)."""
    text = _load_catalog(_current_language).get(key)
    if text is None and _current_language != DEFAULT_LANGUAGE:
        text = _load_catalog(DEFAULT_LANGUAGE).get(key)
    if text is None:
        text = key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
