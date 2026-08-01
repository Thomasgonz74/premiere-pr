import libtorrent as lt

from torrent2000.danger_scanner.models import FileEntry


def files_from_torrent_path(path: str) -> list[FileEntry]:
    """Read a .torrent file's metadata straight off disk -- no session/network
    needed -- so a local file can be analyzed before it is ever added."""
    return files_from_torrent_info(lt.torrent_info(path))


def files_from_torrent_info(ti: "lt.torrent_info") -> list[FileEntry]:
    fs = ti.files()
    entries: list[FileEntry] = []
    for i in range(fs.num_files()):
        flags = fs.file_flags(i)
        if flags & fs.flag_pad_file:
            continue  # internal v2-alignment padding, not a real torrent file
        entries.append(
            FileEntry(
                index=i,
                path=fs.file_path(i),
                size=fs.file_size(i),
                hidden=bool(flags & fs.flag_hidden),
                executable_flag=bool(flags & fs.flag_executable),
            )
        )
    return entries
