from torrent2000.danger_scanner.models import FileEntry, RiskLevel
from torrent2000.danger_scanner.scanner import scan_files


def test_plain_media_file_is_safe():
    files = [FileEntry(index=0, path="Movie.Name.2024.1080p/movie.mkv", size=4_000_000_000)]
    result = scan_files(files, torrent_name="Movie.Name.2024.1080p")
    assert result.file_risks[0].level == RiskLevel.SAFE
    assert result.flagged_indices == []


def test_double_extension_is_flagged_critical():
    files = [FileEntry(index=0, path="Setup_Instructions.pdf.exe", size=500_000)]
    result = scan_files(files)
    risk = result.risk_for_index(0)
    assert risk.level >= RiskLevel.HIGH
    assert 0 in result.flagged_indices


def test_executable_in_mostly_media_torrent_is_flagged():
    files = [
        FileEntry(index=0, path="movie.mkv", size=4_000_000_000),
        FileEntry(index=1, path="subs.srt", size=10_000),
        FileEntry(index=2, path="Codec_Pack_Required.exe", size=2_000_000),
    ]
    result = scan_files(files, torrent_name="Movie")
    risk = result.risk_for_index(2)
    assert risk.level >= RiskLevel.MEDIUM
    assert 2 in result.flagged_indices
    # media files themselves should stay safe
    assert result.risk_for_index(0).level == RiskLevel.SAFE


def test_keygen_named_file_is_flagged():
    files = [FileEntry(index=0, path="Software/keygen.exe", size=100_000)]
    result = scan_files(files)
    risk = result.risk_for_index(0)
    assert risk.level >= RiskLevel.HIGH
    assert len(risk.reasons) >= 2


def test_tiny_executable_is_flagged_lower_than_double_extension():
    tiny_exe = FileEntry(index=0, path="dropper.exe", size=5_000)
    double_ext = FileEntry(index=1, path="invoice.pdf.exe", size=5_000)
    result = scan_files([tiny_exe, double_ext])
    assert result.risk_for_index(0).score < result.risk_for_index(1).score


def test_hidden_file_adds_risk():
    files = [FileEntry(index=0, path=".hidden_payload.exe", size=100_000, hidden=True)]
    result = scan_files(files)
    risk = result.risk_for_index(0)
    assert any("caché" in r for r in risk.reasons)
