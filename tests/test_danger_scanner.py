from torrent2000.danger_scanner.models import FileEntry, RiskLevel
from torrent2000.danger_scanner.rules import RTL_OVERRIDE, ScanContext, SuspiciousNameRule
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


def test_disk_image_file_is_flagged():
    files = [FileEntry(index=0, path="Install/setup.iso", size=700_000_000)]
    result = scan_files(files)
    risk = result.risk_for_index(0)
    assert risk.level >= RiskLevel.LOW
    assert any("Image disque" in r for r in risk.reasons)


def test_macro_document_is_flagged():
    files = [FileEntry(index=0, path="Facture.docm", size=50_000)]
    result = scan_files(files)
    risk = result.risk_for_index(0)
    assert risk.level >= RiskLevel.LOW
    assert any("macros" in r for r in risk.reasons)


def test_executable_flag_without_known_extension_is_flagged():
    files = [FileEntry(index=0, path="payload", size=100_000, executable_flag=True)]
    result = scan_files(files)
    risk = result.risk_for_index(0)
    assert risk.level >= RiskLevel.LOW
    assert any("bit exécutable" in r for r in risk.reasons)


def test_executable_flag_on_known_extension_is_not_double_scored():
    flagged_exe = FileEntry(index=0, path="setup.exe", size=100_000, executable_flag=True)
    unflagged_exe = FileEntry(index=1, path="setup2.exe", size=100_000, executable_flag=False)
    result = scan_files([flagged_exe, unflagged_exe])
    assert result.risk_for_index(0).score == result.risk_for_index(1).score
    assert not any("bit exécutable" in r for r in result.risk_for_index(0).reasons)


def test_suspicious_name_rule_flags_rtl_override_disguised_extension():
    file = FileEntry(index=0, path=f"invoice{RTL_OVERRIDE}fdp.exe", size=100_000)
    context = ScanContext(torrent_name="", media_ratio=0.0)
    hit = SuspiciousNameRule().evaluate(file, context)
    assert hit is not None
    assert hit.score_delta == 70
    assert "RTL-override" in hit.reason


def test_suspicious_name_rule_falls_through_to_keygen_pattern_without_rtl_override():
    file = FileEntry(index=0, path="Software/keygen.exe", size=100_000)
    context = ScanContext(torrent_name="", media_ratio=0.0)
    hit = SuspiciousNameRule().evaluate(file, context)
    assert hit is not None
    assert hit.score_delta == 30
    assert "RTL-override" not in hit.reason


# ---------------------------------------------------------- security fixes
# Regression tests for real bypasses confirmed by a defensive pentest pass
# (see security_test/ and the published pentest report) -- each of these
# previously let a renamed/padded executable through undetected.


def test_double_extension_survives_dot_padding_between_extensions():
    """"facture.pdf.................exe" used to slip past DOUBLE_EXTENSION_RE
    (it required a single literal dot right before the real extension) --
    the padding must not defeat detection."""
    files = [FileEntry(index=0, path="facture_finale.pdf.................exe", size=500_000)]
    result = scan_files(files)
    risk = result.risk_for_index(0)
    assert risk.level >= RiskLevel.HIGH
    assert 0 in result.flagged_indices


def test_normal_sized_plainly_named_executable_alone_is_flagged():
    """A .exe with an ordinary name and a normal (>20KB) size used to score
    25 -- structurally below the MEDIUM threshold (30) -- so a real,
    otherwise-unremarkable executable was never flagged at all."""
    files = [FileEntry(index=0, path="installer.exe", size=500_000)]
    result = scan_files(files)
    risk = result.risk_for_index(0)
    assert risk.level >= RiskLevel.MEDIUM
    assert 0 in result.flagged_indices


def test_unrecognized_extension_gets_a_nonzero_visibility_score():
    """A real executable renamed to an extension outside every fixed list
    (ex .dat/.chm) used to score exactly 0 -- totally invisible. It can't be
    proven dangerous before download (no file bytes exist yet to inspect),
    but it must no longer be silently indistinguishable from a genuinely
    safe file."""
    files = [FileEntry(index=0, path="invoice.dat", size=500_000)]
    result = scan_files(files)
    risk = result.risk_for_index(0)
    assert risk.score > 0
    assert any("inconnue" in reason for reason in risk.reasons)


def test_common_document_and_media_extensions_still_score_zero():
    """The new unknown-extension baseline must not turn every ordinary
    torrent into a wall of false-positive warnings."""
    files = [
        FileEntry(index=0, path="notes.txt", size=1_000),
        FileEntry(index=1, path="cover.jpg", size=200_000),
        FileEntry(index=2, path="archive.zip", size=2_000_000),
    ]
    result = scan_files(files)
    for i in range(3):
        assert result.risk_for_index(i).level == RiskLevel.SAFE
