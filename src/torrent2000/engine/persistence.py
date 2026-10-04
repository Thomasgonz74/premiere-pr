import logging
import os
from pathlib import Path

import libtorrent as lt

from torrent2000.config.paths import get_resume_dir, retry_if_dir_vanished

logger = logging.getLogger(__name__)


def resume_file_path(info_hash: str) -> Path:
    return get_resume_dir() / f"{info_hash}.fastresume"


def save_resume_params(info_hash: str, params: "lt.add_torrent_params") -> None:
    data = lt.write_resume_data_buf(params)

    def _write() -> None:
        path = resume_file_path(info_hash)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_bytes(data)
        os.replace(tmp_path, path)

    # resume/ holds no open handle, so the user can delete it mid-run.
    retry_if_dir_vanished(_write)


def load_all_resume_params() -> list["lt.add_torrent_params"]:
    params = []
    for f in get_resume_dir().glob("*.fastresume"):
        try:
            params.append(lt.read_resume_data(f.read_bytes()))
        except Exception:
            # A truncated write or broken bencode: the torrent is skipped, and
            # the file kept for the user -- but say which one, or it vanishes
            # from the list without a trace.
            logger.warning("Skipping unreadable resume file %s", f.name, exc_info=True)
            continue
    return params


def delete_resume_file(info_hash: str) -> None:
    resume_file_path(info_hash).unlink(missing_ok=True)
