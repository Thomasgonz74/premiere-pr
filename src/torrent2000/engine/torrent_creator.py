"""Builds a .torrent file from a local file or directory.

Torrent 2000 could previously only consume .torrent files (see
engine/torrent_files.py), never produce one. This is the write side, using
libtorrent's own create_torrent (pieces hashed with hashlib, see
_hash_pieces) -- no new dependency needed.

v1_only is forced (rather than libtorrent 2.x's hybrid v1+v2 default): the
hybrid default silently injects v2 alignment padding-file entries, which
would make the reparsed file count no longer match the source file count one
selected. v1_only keeps the output a plain, maximally-compatible torrent
whose file list is exactly what was pointed at.
"""

import hashlib
import os
import threading
from pathlib import Path

import libtorrent as lt


class CreationCancelled(Exception):
    """Raised by create_torrent_file when its `cancel` event gets set."""


def _hash_pieces(ct, base_dir: str, cancel: threading.Event | None) -> None:
    """Fills ct's v1 piece hashes, reading the files in torrent order.

    Done here rather than with lt.set_piece_hashes: that call holds the GIL
    in C++, so even from a worker thread it froze the GUI thread -- for the
    whole hash with the plain overload, and still 0.3-0.7 s per GB (measured,
    all at once after the last piece) with the per-piece-callback one.
    readinto() and sha1() on a whole piece both release the GIL, so the GUI
    thread keeps running, and `cancel` is checked between pieces.
    Pad files would fail the open() -- v1_only never adds them.
    """
    files = ct.files()
    piece_len = ct.piece_length()
    view = memoryview(bytearray(piece_len))
    filled = piece = 0
    for i in range(files.num_files()):
        remaining = files.file_size(i)
        with open(files.file_path(i, base_dir), "rb", buffering=0) as f:
            while remaining:
                n = f.readinto(view[filled : filled + min(remaining, piece_len - filled)])
                if not n:
                    raise OSError(f"{files.file_path(i)} shrank while being hashed")
                filled += n
                remaining -= n
                if filled == piece_len:
                    ct.set_hash(piece, hashlib.sha1(view).digest())
                    piece += 1
                    filled = 0
                    if cancel is not None and cancel.is_set():
                        raise CreationCancelled
    if filled:
        ct.set_hash(piece, hashlib.sha1(view[:filled]).digest())
        piece += 1
    if piece != ct.num_pieces():
        raise OSError(f"hashed {piece} pieces, expected {ct.num_pieces()}")


def create_torrent_file(
    source_path: str,
    output_path: str,
    trackers: list[str],
    piece_size: int = 0,
    private: bool = False,
    comment: str = "",
    cancel: threading.Event | None = None,
) -> None:
    """Creates output_path from source_path (a single file or a directory).

    piece_size=0 lets libtorrent pick an automatic piece size. Raises
    FileNotFoundError if source_path doesn't exist, and RuntimeError if
    piece hashing fails (e.g. a file became unreadable/changed size between
    being selected and being hashed), and CreationCancelled (nothing
    written) once `cancel` is set.
    """
    resolved_source = Path(source_path).resolve()
    if not resolved_source.exists():
        raise FileNotFoundError(source_path)

    file_storage = lt.file_storage()
    lt.add_files(file_storage, str(resolved_source))
    if file_storage.num_files() == 0:
        # add_files() silently no-ops instead of raising on an unreadable
        # source (e.g. an empty directory) -- surface that as a real error
        # rather than letting create_torrent() build a torrent with no files.
        raise ValueError(f"No files found under {source_path}")

    ct = lt.create_torrent(file_storage, piece_size or 0, flags=lt.create_torrent.v1_only)
    ct.set_priv(private)
    for url in trackers:
        url = url.strip()
        if url:
            ct.add_tracker(url)
    ct.set_comment(comment)
    ct.set_creator("Torrent 2000")

    try:
        _hash_pieces(ct, str(resolved_source.parent), cancel)
    except CreationCancelled:
        raise
    except Exception as exc:
        # One clean, always-loggable message whatever the underlying read or
        # libtorrent error was.
        raise RuntimeError(f"Piece hashing failed for {source_path}") from exc

    encoded = lt.bencode(ct.generate())

    out_path = Path(output_path)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_bytes(encoded)
    os.replace(tmp_path, out_path)
