"""Opt-in IP blocklist (catalogue idea "liste noire d'adresses IP") --
OFF BY DEFAULT (see Settings.ip_blocklist_enabled), same convention as every
other opt-in automation in this project.

File format: one CIDR block or IP range per line, "#"-prefixed comments and
blank lines ignored -- deliberately NOT the classic eMule ipfilter.dat format
(which needs a more involved parser for no real benefit here; a plain CIDR
list is what most publicly distributed blocklists are shaped like today).

Complementary to engine/peer_reputation.py: this is an a-priori filter
against known-bad ranges, applied before any connection is made, whereas
peer reputation only ever learns from behavior already observed.
"""

import ipaddress
import logging
import threading

import libtorrent as lt
from PySide6.QtCore import QObject, QRunnable, Signal

logger = logging.getLogger(__name__)

_BLOCK_FLAG = 1  # libtorrent's ip_filter flag meaning "blocked"

# A file in another format (e.g. classic P2P "name:a.b.c.d-e.f.g.h") makes
# every line unparsable: one warning each was ~30 s of logging for a big
# list. Only the first few are logged individually, then one summary.
_MAX_LOGGED_BAD_LINES = 10

# Set once at quit: Qt waits for every running pool task before the process
# exits, and a big list takes seconds to parse. Checked every
# _CANCEL_CHECK_LINES lines.
_cancel_event = threading.Event()
_CANCEL_CHECK_LINES = 4096


def cancel_blocklist_load() -> None:
    """Called once at quit: a running parse stops within a few thousand lines."""
    _cancel_event.set()


class BlocklistLoadCancelled(Exception):
    pass


def parse_blocklist_file(path: str) -> lt.ip_filter:
    """Reads `path` and returns a populated ip_filter. Malformed/unparsable
    lines are skipped (logged), not fatal to the rest of the file --
    consistent with this project's "a malformed line degrades gracefully,
    never crashes the app" convention (e.g. RssSeenStore._load).
    Raises BlocklistLoadCancelled once cancel_blocklist_load() was called."""
    ip_filter = lt.ip_filter()
    bad_lines = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line_number, raw_line in enumerate(f, start=1):
            if line_number % _CANCEL_CHECK_LINES == 0 and _cancel_event.is_set():
                raise BlocklistLoadCancelled
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                first, last = _parse_line(line)
            except ValueError:
                bad_lines += 1
                if bad_lines <= _MAX_LOGGED_BAD_LINES:
                    logger.warning("ip_blocklist: skipping unparsable line %d: %r", line_number, line)
                continue
            ip_filter.add_rule(str(first), str(last), _BLOCK_FLAG)
    if bad_lines > _MAX_LOGGED_BAD_LINES:
        logger.warning("ip_blocklist: skipped %d unparsable lines in total in %r", bad_lines, path)
    return ip_filter


class BlocklistSignals(QObject):
    """QRunnable can't emit signals itself -- same small signal-bus pattern
    as rss_feed_service._RunnableSignals. `loaded` carries the parsed
    ip_filter, or None if the file couldn't be loaded (already logged)."""

    loaded = Signal(object)


class BlocklistLoadRunnable(QRunnable):
    """Parses the blocklist off the GUI thread (~6 s for a 230k-line
    level1 list). Only builds a plain lt.ip_filter value -- applying it to
    the session (set_ip_filter) happens back on the GUI thread, see
    SessionManager._on_ip_blocklist_loaded."""

    def __init__(self, path: str, signals: BlocklistSignals) -> None:
        super().__init__()
        self._path = path
        self._signals = signals

    def run(self) -> None:
        try:
            ip_filter = parse_blocklist_file(self._path)
        except BlocklistLoadCancelled:
            logger.info("IP blocklist load of %r dropped at quit", self._path)
            return
        except Exception:
            # Logged here, not left to escape run() (it would only reach
            # stderr) -- and `loaded` must fire either way, or the session
            # held paused for this filter would never resume.
            logger.exception("Failed to load IP blocklist from %r", self._path)
            ip_filter = None
        if _cancel_event.is_set():
            return  # quitting: the session is shutting down, nothing to apply
        try:
            self._signals.loaded.emit(ip_filter)
        except RuntimeError:
            pass  # signals object deleted by PySide's teardown after the app quit


def _parse_line(line: str) -> tuple:
    if "/" in line:
        network = ipaddress.ip_network(line, strict=False)
        return network.network_address, network.broadcast_address
    if "-" in line:
        first_str, last_str = (part.strip() for part in line.split("-", 1))
        first = ipaddress.ip_address(first_str)
        last = ipaddress.ip_address(last_str)
        if last < first:
            raise ValueError(f"range end before start: {line!r}")
        return first, last
    # A bare address blocks just that one IP (first == last).
    addr = ipaddress.ip_address(line)
    return addr, addr
