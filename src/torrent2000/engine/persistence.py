import os
from pathlib import Path

import libtorrent as lt

from torrent2000.config.paths import get_resume_dir


def resume_file_path(info_hash: str) -> Path:
    return get_resume_dir() / f"{info_hash}.fastresume"


def save_resume_params(info_hash: str, params: "lt.add_torrent_params") -> None:
    data = lt.write_resume_data_buf(params)
    path = resume_file_path(info_hash)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(data)
    os.replace(tmp_path, path)


def load_all_resume_params() -> list["lt.add_torrent_params"]:
    params = []
    for f in get_resume_dir().glob("*.fastresume"):
        try:
            params.append(lt.read_resume_data(f.read_bytes()))
        except Exception:
            continue
    return params


def delete_resume_file(info_hash: str) -> None:
    resume_file_path(info_hash).unlink(missing_ok=True)
