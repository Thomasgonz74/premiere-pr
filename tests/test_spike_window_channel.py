"""Every QWebChannel object the web UI uses must be registered by
SpikeWindow: an unregistered one is simply undefined in JS (PieceMapBridge
never was, so the piece map dialog threw a TypeError instead of opening)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_bridge_object_the_web_ui_uses_is_registered():
    used = set()
    for js_file in (ROOT / "resources" / "web" / "spike").glob("*.js"):
        source = js_file.read_text(encoding="utf-8")
        used.update(re.findall(r"(?:window\.bridge|channel\.objects)\??\.([A-Za-z_$][\w$]*)", source))
    spike_window = (ROOT / "src" / "torrent2000" / "ui" / "web" / "spike_window.py").read_text(encoding="utf-8")
    registered = set(re.findall(r'registerObject\(\s*"(\w+)"', spike_window))

    assert "downloads" in used  # the pattern still finds the JS usages
    assert used - registered == set()
