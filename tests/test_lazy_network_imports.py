"""url_fetch.py and remote_server.py are imported at every launch, but the
http.client/ssl/email.* stack behind urllib.request and http.server is only
needed by the first real fetch / the first remote-access start (off by
default) -- both modules import it lazily. Checked in a fresh interpreter,
since this test process has long since imported all of it."""

import os
import subprocess
import sys
from pathlib import Path


def test_importing_the_network_modules_does_not_load_the_http_stack():
    src = Path(__file__).resolve().parent.parent / "src"
    code = (
        "import sys, torrent2000.engine.url_fetch, torrent2000.engine.remote_server; "
        "print(sorted(m for m in ('http.client', 'http.server', 'ssl', 'urllib.request') if m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(src)},
        timeout=60,
        check=True,
    )
    assert result.stdout.strip() == "[]"
