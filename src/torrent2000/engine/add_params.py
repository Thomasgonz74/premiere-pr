import libtorrent as lt

FILE_PRIORITY_EXCLUDED = 0
FILE_PRIORITY_DEFAULT = 4


_DISCOVERY_FLAGS = (
    lt.torrent_flags.disable_dht | lt.torrent_flags.disable_pex | lt.torrent_flags.disable_lsd
)


def from_torrent_file(
    path: str,
    save_path: str,
    excluded_indices: "set[int] | None" = None,
    restrict_discovery: bool = False,
) -> "lt.add_torrent_params":
    ti = lt.torrent_info(path)
    atp = lt.add_torrent_params()
    atp.ti = ti
    atp.save_path = save_path
    atp.flags |= lt.torrent_flags.duplicate_is_error
    if restrict_discovery:
        atp.flags |= _DISCOVERY_FLAGS
    if excluded_indices:
        num_files = ti.files().num_files()
        atp.file_priorities = [
            FILE_PRIORITY_EXCLUDED if i in excluded_indices else FILE_PRIORITY_DEFAULT
            for i in range(num_files)
        ]
    return atp


def from_magnet_uri(uri: str, save_path: str, restrict_discovery: bool = False) -> "lt.add_torrent_params":
    atp = lt.parse_magnet_uri(uri)
    atp.save_path = save_path
    if restrict_discovery:
        atp.flags |= _DISCOVERY_FLAGS
    return atp


def from_resume_data(data: bytes) -> "lt.add_torrent_params":
    return lt.read_resume_data(data)


def info_hash_hex(atp: "lt.add_torrent_params") -> str:
    # add_torrent_params.info_hashes is only populated by libtorrent once the
    # torrent has actually been added to a session; when building params from
    # a .torrent file (atp.ti set) the hash must be read from the torrent_info
    # itself instead.
    hashes = atp.ti.info_hashes() if atp.ti is not None else atp.info_hashes
    if hashes.has_v1():
        return str(hashes.v1)
    return str(hashes.v2)
