"""QWebChannel bridge delivering the i18n catalog to the web UI. The
fallback-to-French merge already happens on the Python side (see
i18n/translator.py::effective_catalog) so resources/web/spike/i18n.js is a
plain flat-dict lookup, not a second implementation of the fallback rule.
"""

from PySide6.QtCore import QObject, Slot

from torrent2000.i18n.translator import effective_catalog


class I18nBridge(QObject):
    @Slot(result="QVariantMap")
    def getCatalog(self) -> dict:
        return effective_catalog()
