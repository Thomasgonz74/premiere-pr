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
