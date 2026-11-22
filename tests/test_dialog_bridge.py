"""DialogBridge's native file dialogs, titled in the UI language (stubbed:
nothing opens)."""

import json
from pathlib import Path

from torrent2000.i18n import translator
from torrent2000.ui.web import dialog_bridge
from torrent2000.ui.web.dialog_bridge import DialogBridge


def test_file_dialogs_are_titled_in_the_ui_language(monkeypatch):
    english = json.loads(
        (Path(__file__).resolve().parents[1] / "resources" / "i18n" / "en.json").read_text(encoding="utf-8")
    )
    captions = []
    dialog = dialog_bridge.QFileDialog
    monkeypatch.setattr(dialog, "getExistingDirectory", lambda parent, caption, folder: captions.append(caption) or "")
    monkeypatch.setattr(dialog, "getOpenFileName", lambda parent, caption, *a: captions.append(caption) or ("", ""))
    monkeypatch.setattr(dialog, "getSaveFileName", lambda parent, caption, *a: captions.append(caption) or ("", ""))
    bridge = DialogBridge(None)
    translator.set_language("en")
    try:
        bridge.browseFolder("")
        bridge.browseTorrentFile()
        bridge.browseSaveFile("history.csv", "CSV (*.csv)")
        bridge.browseOpenFile("*.txt")
    finally:
        translator.set_language(translator.DEFAULT_LANGUAGE)

    assert captions == [
        english["web.dialogs.choose_folder_title"],
        english["add_tab.choose_torrent_title"],
        english["web.dialogs.save_as_title"],
        english["web.dialogs.choose_file_title"],
    ]
