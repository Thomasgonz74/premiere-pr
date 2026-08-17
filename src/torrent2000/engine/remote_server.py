"""Small local-network HTTP server so torrent progress can be checked (and a
share paused/resumed) from a phone on the same LAN.

OFF BY DEFAULT (see Settings.remote_access_enabled) -- nothing here binds a
socket unless the user has explicitly opted in from the Profile tab. Once
running, this listens on every interface (0.0.0.0), not just localhost --
that's required for a phone to reach it at all, which also means anyone else
on that same network can technically open a connection to it. The ONLY thing
that stops them acting on it is Settings.remote_access_token: every single
route, including the plain HTML page, refuses to do anything at all without
it. There is no session/cookie -- the token travels as a `?token=` query
parameter on every request (including the ones the embedded page's own JS
makes), chosen over HTTP Basic Auth because it's what a phone's browser can
actually be handed as one plain URL (typed once, or opened from a saved
link/QR code) without a credential prompt some mobile browsers mishandle for
non-HTTPS origins. This is NOT a substitute for encryption -- there is no
TLS here, so the token is visible to anything that can already see LAN
traffic -- only ever use this on a network you trust.

Token comparison uses hmac.compare_digest rather than == to avoid a timing
side-channel that could help an attacker guess the token character by
character.

Serves exactly three things, nothing else -- in particular, NOT a generic
file server (no SimpleHTTPRequestHandler, no path-to-disk mapping of any
kind), so there is no path-traversal surface to worry about:
  - GET  /                          the embedded HTML/JS page (constant, no
                                     server-side templating of user data)
  - GET  /api/torrents              JSON list of current torrents
  - POST /api/torrents/<hash>/pause   pause that torrent
  - POST /api/torrents/<hash>/resume  resume that torrent

Runs on a dedicated background thread (ThreadingHTTPServer's own
serve_forever loop, itself spawning one short-lived thread per request) so
it can never block the Qt GUI thread. start()/stop() are idempotent -- a
second start() while already running, or a stop() while not running, is a
harmless no-op.
"""

import hmac
import json
import logging
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from torrent2000.config.settings import Settings
from torrent2000.engine.session_manager import SessionManager

logger = logging.getLogger(__name__)

# Bound to every interface (see module docstring) -- this is deliberate, not
# an oversight, and is exactly why remote_access_token is non-negotiable.
_BIND_HOST = "0.0.0.0"

_REMOTE_ACCESS_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Torrent 2000 Remote</title>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 12px;
         background: #111318; color: #eaeaea; }
  h1 { font-size: 1.05rem; margin: 0 0 12px; }
  #status { color: #ff6b6b; min-height: 1.2em; margin-bottom: 8px; font-size: 0.85rem; }
  .torrent { border: 1px solid #2c2f3a; border-radius: 10px; padding: 10px 12px; margin-bottom: 10px; }
  .name { font-weight: 600; word-break: break-all; margin-bottom: 6px; }
  .bar { background: #23262f; border-radius: 4px; height: 8px; overflow: hidden; margin-bottom: 6px; }
  .fill { background: #4caf50; height: 100%; }
  .meta { font-size: 0.8rem; color: #a3a7b3; margin-bottom: 8px; }
  button { padding: 6px 14px; border-radius: 6px; border: none; background: #3a6df0; color: #fff;
           font-size: 0.85rem; }
  button:active { opacity: 0.8; }
  #empty { color: #a3a7b3; font-size: 0.9rem; }
</style>
</head>
<body>
<h1>Torrent 2000 - Remote access</h1>
<div id="status"></div>
<div id="empty" hidden>No torrents.</div>
<div id="list"></div>
<script>
(function () {
  "use strict";
  var token = new URLSearchParams(window.location.search).get("token") || "";

  function withToken(path) {
    var sep = path.indexOf("?") === -1 ? "?" : "&";
    return path + sep + "token=" + encodeURIComponent(token);
  }

  function fmtRate(bytesPerSec) {
    var kb = (bytesPerSec || 0) / 1024;
    if (kb < 1024) return kb.toFixed(0) + " KB";
    return (kb / 1024).toFixed(1) + " MB";
  }

  function toggle(infoHash, isPaused) {
    var action = isPaused ? "resume" : "pause";
    fetch(withToken("/api/torrents/" + encodeURIComponent(infoHash) + "/" + action), { method: "POST" })
      .then(refresh)
      .catch(function () {});
  }

  function render(torrents) {
    var list = document.getElementById("list");
    var empty = document.getElementById("empty");
    list.innerHTML = "";
    empty.hidden = torrents.length !== 0;
    torrents.forEach(function (t) {
      var pct = Math.round((t.progress || 0) * 100);
      var isPaused = t.state === "PAUSED";

      var row = document.createElement("div");
      row.className = "torrent";

      // textContent everywhere below -- torrent names come from .torrent
      // files/trackers, i.e. untrusted input, so this must never be
      // assigned via innerHTML.
      var nameEl = document.createElement("div");
      nameEl.className = "name";
      nameEl.textContent = t.name || t.info_hash;
      row.appendChild(nameEl);

      var barEl = document.createElement("div");
      barEl.className = "bar";
      var fillEl = document.createElement("div");
      fillEl.className = "fill";
      fillEl.style.width = pct + "%";
      barEl.appendChild(fillEl);
      row.appendChild(barEl);

      var metaEl = document.createElement("div");
      metaEl.className = "meta";
      metaEl.textContent = pct + "% - " + t.state + " - down " + fmtRate(t.download_rate) +
        "/s - up " + fmtRate(t.upload_rate) + "/s";
      row.appendChild(metaEl);

      var btn = document.createElement("button");
      btn.textContent = isPaused ? "Resume" : "Pause";
      btn.addEventListener("click", function () { toggle(t.info_hash, isPaused); });
      row.appendChild(btn);

      list.appendChild(row);
    });
  }

  function refresh() {
    fetch(withToken("/api/torrents"))
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        document.getElementById("status").textContent = "";
        render(data.torrents || []);
      })
      .catch(function (err) {
        document.getElementById("status").textContent = "Connection error: " + err.message;
      });
  }

  refresh();
  setInterval(refresh, 3000);
})();
</script>
</body>
</html>
"""


def _torrent_to_json(record) -> dict:
    return {
        "info_hash": record.info_hash,
        "name": record.name,
        "progress": record.progress,
        "state": record.state.name,
        "download_rate": record.download_rate,
        "upload_rate": record.upload_rate,
    }


class _RemoteAccessHandler(BaseHTTPRequestHandler):
    """session_manager/settings are stashed on `self.server` by
    RemoteAccessServer.start() rather than baked into a per-instance
    subclass -- BaseHTTPRequestHandler always instantiates its handler class
    itself (one instance per request) with a fixed (request, client_address,
    server) signature, so there's no constructor hook to inject them any
    other way."""

    server_version = "Torrent2000RemoteAccess/1"

    def log_message(self, format: str, *args) -> None:
        # Overridden so a request's query string (which carries the token)
        # never reaches stderr/any log file via the default implementation --
        # route through the app's own logger at debug level, path only,
        # never the query string.
        logger.debug("remote_access %s - %s %s", self.address_string(), self.command, urlsplit(self.path).path)

    def _token_is_valid(self) -> bool:
        expected = self.server.settings.remote_access_token  # type: ignore[attr-defined]
        if not expected:
            return False  # feature not actually started/provisioned yet -- deny everything
        query = parse_qs(urlsplit(self.path).query)
        provided = query.get("token", [""])[0]
        return hmac.compare_digest(provided, expected)

    def _require_token(self) -> bool:
        if self._token_is_valid():
            return True
        self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        return False

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler's own naming convention)
        if not self._require_token():
            return
        path = urlsplit(self.path).path
        if path == "/":
            self._send_html(_REMOTE_ACCESS_PAGE_HTML)
        elif path == "/api/torrents":
            session_manager: SessionManager = self.server.session_manager  # type: ignore[attr-defined]
            torrents = [_torrent_to_json(record) for record in session_manager.all_records()]
            self._send_json(HTTPStatus.OK, {"torrents": torrents})
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._require_token():
            return
        path = urlsplit(self.path).path
        parts = path.split("/")
        # ["", "api", "torrents", "<info_hash>", "pause"|"resume"]
        if len(parts) == 5 and parts[1] == "api" and parts[2] == "torrents" and parts[4] in ("pause", "resume"):
            info_hash = parts[3]
            session_manager: SessionManager = self.server.session_manager  # type: ignore[attr-defined]
            if parts[4] == "pause":
                session_manager.pause_torrent(info_hash)
            else:
                session_manager.resume_torrent(info_hash)
            self._send_json(HTTPStatus.OK, {"ok": True})
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _Server(ThreadingHTTPServer):
    # Request-handling threads (ThreadingMixIn spawns one per connection)
    # must not outlive the process/keep it alive on their own -- daemonize
    # them so a slow/hanging client can never block shutdown.
    daemon_threads = True
    # Stashed here by RemoteAccessServer.start() -- see _RemoteAccessHandler's
    # docstring for why this is how the handler gets at them.
    session_manager: SessionManager
    settings: Settings


class RemoteAccessServer:
    """Owns the actual listening socket. Construct once, call start()/stop()
    as needed -- both are safe to call repeatedly (idempotent)."""

    def __init__(self, session_manager: SessionManager, settings: Settings) -> None:
        self._session_manager = session_manager
        self._settings = settings
        self._httpd: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._httpd is not None

    @property
    def bound_port(self) -> int:
        """The actual bound port -- same as settings.remote_access_port
        except in tests, which bind port 0 (OS-assigned) to avoid clashing
        with anything else using the real configured port. 0 if not running."""
        return self._httpd.server_address[1] if self._httpd is not None else 0

    def start(self) -> bool:
        """Returns whether a socket actually ended up bound and listening --
        callers must check this (or is_running afterwards) rather than
        assuming success, since a bind failure is caught and logged here
        instead of raising, and self._settings.remote_access_token being set
        is NOT proof of a running server: the token is provisioned before the
        bind attempt (see comment below) so it exists either way."""
        if self._httpd is not None:
            return True  # already running
        if not self._settings.remote_access_token:
            # Generated here rather than in Settings itself -- this way a
            # token only ever comes into existence the first time the
            # feature is actually turned on, never eagerly at Settings()
            # construction (which would mean every install, even ones that
            # never touch this feature, silently has a live secret sitting
            # in its config file).
            self._settings.remote_access_token = secrets.token_urlsafe(24)
            self._settings.save()
        try:
            httpd = _Server((_BIND_HOST, self._settings.remote_access_port), _RemoteAccessHandler)
        except OSError:
            logger.exception(
                "Remote access server failed to bind port %s -- leaving the feature effectively off",
                self._settings.remote_access_port,
            )
            return False
        httpd.session_manager = self._session_manager
        httpd.settings = self._settings
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, name="RemoteAccessServer", daemon=True)
        self._thread.start()
        logger.info("Remote access server listening on port %s", self.bound_port)
        return True

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._httpd = None
        self._thread = None
        logger.info("Remote access server stopped")
