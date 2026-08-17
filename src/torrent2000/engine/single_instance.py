"""Single-instance guard built on QLocalServer/QLocalSocket (a named pipe
on Windows, a Unix domain socket elsewhere -- already part of PySide6, no
new dependency).

Launching the app a second time is a realistic everyday scenario now that
the installer registers .torrent/magnet: file associations: double-clicking
a second .torrent file while the app is already open must hand that path to
the already-running instance and exit, rather than starting a second
competing libtorrent session against the same ports and download
directories.

try_become_primary() first probes for an already-listening instance as a
plain client; only if nothing answers does it become the server itself.
This ordering means two processes racing to start at the same instant both
try the client probe first -- at most one of them can end up listening,
and the loser's later listen() failure is treated as a non-critical,
best-effort miss (logged, startup proceeds anyway) rather than blocking
the app over what is fundamentally a convenience feature.
"""

import logging

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

_SERVER_NAME = "Torrent2000SingleInstance"
_CONNECT_TIMEOUT_MS = 500


class SingleInstanceGuard(QObject):
    """Call try_become_primary() exactly once, as the very first thing on
    startup. If it returns False, another instance is already running and
    has been sent forward_argument -- the caller must exit immediately
    without doing any further startup work. If it returns True, this
    process is now the primary instance and must keep the guard alive for
    the app's lifetime (its QLocalServer stops listening as soon as the
    guard is garbage-collected); connect argument_received to handle
    arguments forwarded by later launches."""

    argument_received = Signal(str)  # forwarded .torrent path or magnet: URI; may be ""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._server: QLocalServer | None = None
        self._pending_sockets: list[QLocalSocket] = []

    def try_become_primary(self, forward_argument: str) -> bool:
        if self._forward_to_running_instance(forward_argument):
            return False
        self._start_listening()
        return True

    def close(self) -> None:
        """Stops listening and releases the server socket/pipe immediately.
        Production code doesn't need this -- the OS reclaims a listening
        named pipe/socket the moment the process exits -- but tests that
        create more than one guard in the same process need deterministic
        teardown between them rather than waiting on Python's cyclic GC to
        eventually collect the guard<->server<->socket reference cycles
        this class otherwise relies on to stay alive for the app's
        lifetime."""
        # Flush any deleteLater() already scheduled by _on_socket_disconnected
        # while the socket's parent (self._server) is still valid -- otherwise
        # closing/dropping the server below could end up deleting that same
        # socket a second time whenever the deferred-delete event is
        # eventually processed.
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        for socket in list(self._pending_sockets):
            try:
                socket.disconnected.disconnect()
                socket.abort()
            except RuntimeError:
                pass  # already gone
        self._pending_sockets.clear()
        if self._server is not None:
            self._server.newConnection.disconnect(self._accept_pending_connection)
            self._server.close()
            self._server = None

    def _forward_to_running_instance(self, forward_argument: str) -> bool:
        """Returns True if an already-running instance accepted the
        connection and was sent forward_argument; False if nothing is
        listening (the normal case: this is the first/only instance)."""
        socket = QLocalSocket(self)
        socket.connectToServer(_SERVER_NAME)
        if not socket.waitForConnected(_CONNECT_TIMEOUT_MS):
            socket.abort()
            return False
        socket.write(forward_argument.encode("utf-8"))
        socket.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
        socket.disconnectFromServer()
        return True

    def _start_listening(self) -> None:
        server = QLocalServer(self)
        server.newConnection.connect(self._accept_pending_connection)
        if not server.listen(_SERVER_NAME):
            # A previous instance that crashed instead of shutting down
            # cleanly can leave a stale server socket behind; clear it and
            # retry once before giving up.
            QLocalServer.removeServer(_SERVER_NAME)
            server.listen(_SERVER_NAME)
        if not server.isListening():
            logger.warning(
                "Could not start single-instance server (%s); a second launch "
                "will start its own session instead of being forwarded here.",
                server.errorString(),
            )
        self._server = server

    def _accept_pending_connection(self) -> None:
        server = self._server
        if server is None:
            return
        socket = server.nextPendingConnection()
        if socket is None:
            return
        self._pending_sockets.append(socket)
        # Reading only on disconnected (not readyRead) is deliberate: an
        # empty forward_argument means the client writes zero bytes, which
        # never triggers readyRead at all, so readyRead alone would silently
        # drop that case. The client always writes its full payload (however
        # short) and flushes it via waitForBytesWritten() before calling
        # disconnectFromServer(), so by the time disconnected fires here, a
        # single readAll() reliably has the complete forwarded string.
        socket.disconnected.connect(lambda: self._on_socket_disconnected(socket))

    def _on_socket_disconnected(self, socket: QLocalSocket) -> None:
        forwarded = bytes(socket.readAll()).decode("utf-8", errors="replace")
        self.argument_received.emit(forwarded)
        if socket in self._pending_sockets:
            self._pending_sockets.remove(socket)
        try:
            socket.deleteLater()
        except RuntimeError:
            pass  # the underlying C++ object is already gone (e.g. its parent server was torn down first)
