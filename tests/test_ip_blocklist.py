"""Parsing tests for the opt-in IP blocklist (see engine/ip_blocklist.py):
CIDR blocks, IP ranges, bare addresses, comments/blank lines, and graceful
skipping of unparsable lines."""

import logging
import threading
from unittest.mock import MagicMock

from PySide6.QtCore import QObject

from torrent2000.engine import ip_blocklist
from torrent2000.engine import session_manager as session_manager_module
from torrent2000.engine.ip_blocklist import BlocklistLoadRunnable, BlocklistSignals, parse_blocklist_file
from torrent2000.engine.session_manager import SessionManager


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


def test_unparsable_lines_are_logged_individually_only_up_to_a_cap(tmp_path, caplog):
    """A file in another format makes every line unparsable -- one warning
    per line was ~30 s of logging for a big list."""
    content = "".join(f"name{i}:1.2.3.{i}-1.2.3.{i}\n" for i in range(50)) + "1.2.3.0/24\n"
    with caplog.at_level(logging.WARNING, logger="torrent2000.engine.ip_blocklist"):
        ip_filter = parse_blocklist_file(_write(tmp_path, content))

    assert ip_filter.access("1.2.3.5") == 1
    assert len(caplog.records) == 11  # the first 10 lines + one summary
    assert "50 unparsable lines" in caplog.records[-1].getMessage()


def _session_manager_loading_inline(monkeypatch, calls):
    """SessionManager with a mock lt.session whose blocklist runnable runs
    synchronously (so its signal is delivered directly), recording the
    order of pause/parse/set_ip_filter/resume."""
    sm = SessionManager.__new__(SessionManager)  # bypass __init__, no real libtorrent session needed
    QObject.__init__(sm)
    sm._session = MagicMock()
    sm._session.pause.side_effect = lambda: calls.append("pause")
    sm._session.set_ip_filter.side_effect = lambda f: calls.append(("filter", f.access("1.2.3.5")))
    sm._session.resume.side_effect = lambda: calls.append("resume")
    sm._paused_for_ip_blocklist = False
    sm._timer = MagicMock()  # the tick timer, active until shutdown()
    pool = MagicMock()
    pool.globalInstance.return_value.start.side_effect = lambda runnable: (calls.append("parse"), runnable.run())
    monkeypatch.setattr(session_manager_module, "QThreadPool", pool)
    return sm


def test_session_stays_paused_until_the_parsed_filter_is_applied(tmp_path, monkeypatch):
    calls = []
    sm = _session_manager_loading_inline(monkeypatch, calls)

    sm._load_ip_blocklist(_write(tmp_path, "1.2.3.0/24\n"))

    assert calls == ["pause", "parse", ("filter", 1), "resume"]


def test_the_wait_is_signalled_and_readable_while_it_lasts(tmp_path, monkeypatch):
    """The Downloads page's notice: shown for the whole pause, hidden once
    the filter is applied (a page loading late asks the getter)."""
    calls = []
    sm = _session_manager_loading_inline(monkeypatch, calls)
    seen = []
    sm.ip_blocklist_wait_changed.connect(lambda waiting: seen.append((waiting, sm.is_waiting_for_ip_blocklist())))

    sm._load_ip_blocklist(_write(tmp_path, "1.2.3.0/24\n"))

    assert seen == [(True, True), (False, False)]


def test_missing_file_is_logged_and_the_session_resumed_without_a_filter(tmp_path, monkeypatch, caplog):
    calls = []
    sm = _session_manager_loading_inline(monkeypatch, calls)

    with caplog.at_level(logging.ERROR, logger="torrent2000.engine.ip_blocklist"):
        sm._load_ip_blocklist(str(tmp_path / "missing.txt"))

    assert calls == ["pause", "parse", "resume"]
    assert "Failed to load IP blocklist" in caplog.text
    assert not sm.is_waiting_for_ip_blocklist()  # the load ended: notice hidden


def test_the_pause_never_waits_on_libtorrent_network_thread(tmp_path, monkeypatch):
    """Called from SessionManager.__init__: is_paused() is a blocking round
    trip to the network thread (pause() is queued), and a fresh session is
    never paused anyway."""
    calls = []
    sm = _session_manager_loading_inline(monkeypatch, calls)
    sm._session.is_paused.side_effect = AssertionError("blocking call")

    sm._load_ip_blocklist(_write(tmp_path, "1.2.3.0/24\n"))

    assert calls == ["pause", "parse", ("filter", 1), "resume"]


def test_quit_stops_the_parse_and_reports_nothing(tmp_path, monkeypatch):
    """Qt waits for this runnable before the process exits, and its signals
    object may already be deleted by then."""
    monkeypatch.setattr(ip_blocklist, "_cancel_event", threading.Event())
    total_lines = 20000
    path = _write(tmp_path, "1.2.3.0/24\n" * total_lines)
    parsed = []
    real_parse_line = ip_blocklist._parse_line
    monkeypatch.setattr(ip_blocklist, "_parse_line", lambda line: (parsed.append(line), real_parse_line(line))[1])
    signals = BlocklistSignals()
    loaded = []
    signals.loaded.connect(loaded.append)

    ip_blocklist.cancel_blocklist_load()
    BlocklistLoadRunnable(path, signals).run()

    assert len(parsed) < total_lines
    assert loaded == []


def test_a_filter_arriving_during_shutdown_does_not_resume_the_session(monkeypatch):
    """shutdown() pumps events while saving resume data; a parse finishing
    then must not resume the session it is closing."""
    calls = []
    sm = _session_manager_loading_inline(monkeypatch, calls)
    sm._paused_for_ip_blocklist = True
    sm._timer.isActive.return_value = False  # shutdown() stops it first

    sm._on_ip_blocklist_loaded(None)

    assert calls == []
