"""Parsing tests for the opt-in IP blocklist (see engine/ip_blocklist.py):
CIDR blocks, IP ranges, bare addresses, comments/blank lines, and graceful
skipping of unparsable lines."""

from torrent2000.engine.ip_blocklist import parse_blocklist_file


def _write(tmp_path, content):
    path = tmp_path / "blocklist.txt"
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_cidr_block_is_blocked(tmp_path):
    ip_filter = parse_blocklist_file(_write(tmp_path, "1.2.3.0/24\n"))
    assert ip_filter.access("1.2.3.5") == 1
    assert ip_filter.access("8.8.8.8") == 0


def test_ip_range_is_blocked(tmp_path):
    ip_filter = parse_blocklist_file(_write(tmp_path, "10.0.0.1 - 10.0.0.10\n"))
    assert ip_filter.access("10.0.0.5") == 1
    assert ip_filter.access("10.0.0.20") == 0


def test_bare_address_blocks_only_that_ip(tmp_path):
    ip_filter = parse_blocklist_file(_write(tmp_path, "203.0.113.7\n"))
    assert ip_filter.access("203.0.113.7") == 1
    assert ip_filter.access("203.0.113.8") == 0


def test_comments_and_blank_lines_are_ignored(tmp_path):
    ip_filter = parse_blocklist_file(_write(tmp_path, "# a comment\n\n1.2.3.0/24\n"))
    assert ip_filter.access("1.2.3.5") == 1


def test_unparsable_line_is_skipped_not_fatal(tmp_path):
    ip_filter = parse_blocklist_file(_write(tmp_path, "not-an-ip-or-range\n1.2.3.0/24\n"))
    assert ip_filter.access("1.2.3.5") == 1


def test_reversed_range_is_skipped(tmp_path):
    ip_filter = parse_blocklist_file(_write(tmp_path, "10.0.0.10 - 10.0.0.1\n1.2.3.0/24\n"))
    assert ip_filter.access("1.2.3.5") == 1
    assert ip_filter.access("10.0.0.5") == 0
