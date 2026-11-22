"""I18nBridge is a one-method pass-through to translator.effective_catalog()
(see ui/web/bridge_i18n.py) -- covered here rather than left to the smoke
test since it's the only thing standing between a wrong language on disk and
every page rendering raw i18n keys instead of text."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from torrent2000.i18n import translator
from torrent2000.ui.web.bridge_i18n import I18nBridge


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def test_get_catalog_reflects_the_active_language():
    translator.set_language("fr")
    try:
        bridge = I18nBridge()
        assert bridge.getCatalog()["common.cancel"] == "Annuler"
    finally:
        translator.set_language(translator.DEFAULT_LANGUAGE)


def _catalog(lang: str) -> dict:
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "resources" / "i18n" / f"{lang}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_bridge_messages_follow_the_language(tmp_path, monkeypatch):
    """Returned as hard-coded French whatever the language."""
    from unittest.mock import MagicMock

    from torrent2000.config.settings import Settings
    from torrent2000.engine.routing_rules import RoutingRuleStore
    from torrent2000.ui.web.bridge_add import AddBridge
    from torrent2000.ui.web.bridge_known_disk import KnownDiskBridge
    from torrent2000.ui.web.bridge_profile_security import ProfileSecurityBridge
    from torrent2000.ui.web.bridge_rss import RssBridge
    from torrent2000.ui.web.bridge_share import ShareBridge

    monkeypatch.setenv("TORRENT2000_DATA_DIR", str(tmp_path))
    english = _catalog("en")
    settings = Settings()
    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    translator.set_language("en")
    try:
        errors = [
            AddBridge(MagicMock(), settings, RoutingRuleStore()).startTorrent("", "", "", [])["error"],
            ShareBridge(MagicMock(), MagicMock(), settings).startShare("", "", 0, 0, 0.0)["error"],
            RssBridge(MagicMock(), MagicMock(), settings).addFeed("", "")["error"],
            KnownDiskBridge(MagicMock(), MagicMock(), MagicMock()).saveDisk("", "")["error"],
            ProfileSecurityBridge(settings).importConfig(str(broken))["error"],
        ]
    finally:
        translator.set_language(translator.DEFAULT_LANGUAGE)

    assert errors == [
        english["add_tab.no_source_message"],
        english["share_tab.missing_dir_message"],
        english["web.rss.url_required"],
        english["web.profile_automation.known_disk_label_required"],
        english["profile_tab.import_failed_message_invalid"],
    ]


def test_every_static_help_bubble_is_translated():
    """Four '?' bubbles of index.html were French in every language."""
    import re
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "resources" / "web" / "spike" / "index.html").read_text(
        encoding="utf-8"
    )
    bubbles = re.findall(r"<[^>]*\bdata-tooltip=[^>]*>", html)
    keys = re.findall(r'data-i18n-tooltip="([^"]+)"', html)

    assert bubbles and all("data-i18n-tooltip=" in tag for tag in bubbles)
    for lang in ("fr", "en", "de", "es", "it", "pt", "pl", "ru", "ja", "ko", "zh"):
        catalog = _catalog(lang)
        assert [key for key in keys if key not in catalog] == [], lang
