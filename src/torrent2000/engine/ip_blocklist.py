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

import libtorrent as lt

logger = logging.getLogger(__name__)

_BLOCK_FLAG = 1  # libtorrent's ip_filter flag meaning "blocked"


def parse_blocklist_file(path: str) -> lt.ip_filter:
    """Reads `path` and returns a populated ip_filter. Malformed/unparsable
    lines are skipped (logged), not fatal to the rest of the file --
    consistent with this project's "a malformed line degrades gracefully,
    never crashes the app" convention (e.g. RssSeenStore._load)."""
    ip_filter = lt.ip_filter()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line_number, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                first, last = _parse_line(line)
            except ValueError:
                logger.warning("ip_blocklist: skipping unparsable line %d: %r", line_number, line)
                continue
            ip_filter.add_rule(str(first), str(last), _BLOCK_FLAG)
    return ip_filter


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
