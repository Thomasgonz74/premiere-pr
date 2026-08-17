"""Builds a .torrent file from a local file or directory.

Torrent 2000 could previously only consume .torrent files (see
engine/torrent_files.py), never produce one. This is the write side, using
libtorrent's own create_torrent/set_piece_hashes -- no new dependency needed.

v1_only is forced (rather than libtorrent 2.x's hybrid v1+v2 default): the
hybrid default silently injects v2 alignment padding-file entries, which
would make the reparsed file count no longer match the source file count one
selected. v1_only keeps the output a plain, maximally-compatible torrent
whose file list is exactly what was pointed at.
"""

import os
from pathlib import Path

import libtorrent as lt


def create_torrent_file(
    source_path: str,
    output_path: str,
    trackers: list[str],
    piece_size: int = 0,
    private: bool = False,
    comment: str = "",
) -> None:
    """Creates output_path from source_path (a single file or a directory).

    piece_size=0 lets libtorrent pick an automatic piece size. Raises
    FileNotFoundError if source_path doesn't exist, and RuntimeError if
    piece hashing fails (e.g. a file became unreadable/changed size between
    being selected and being hashed).
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
        lt.set_piece_hashes(ct, str(resolved_source.parent))
    except Exception as exc:
        # libtorrent's own exception here can carry a non-UTF-8-decodable
        # message (observed as a raw UnicodeDecodeError from boost.python
        # itself rather than a clean RuntimeError) -- wrap it in a message
        # that's always safe to log/display instead of propagating that as-is.
        raise RuntimeError(f"Piece hashing failed for {source_path}") from exc

    encoded = lt.bencode(ct.generate())

    out_path = Path(output_path)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_bytes(encoded)
    os.replace(tmp_path, out_path)
