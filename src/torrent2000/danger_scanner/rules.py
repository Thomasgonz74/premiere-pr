import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from torrent2000.danger_scanner.models import FileEntry

EXECUTABLE_EXTENSIONS = {
    "exe", "bat", "cmd", "com", "js", "jse", "vbs", "vbe", "wsf", "wsh",
    "ps1", "jar", "scr", "pif", "msi", "lnk", "hta", "cpl", "gadget", "reg",
}

MEDIA_EXTENSIONS = {
    "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "mp3", "flac", "wav",
    "aac", "ogg", "m4a", "srt", "sub", "idx", "nfo",
}

# Mounting one of these sidesteps Windows SmartScreen's "mark of the web"
# check, since the executable run from inside the mounted volume never
# itself carries the web-origin flag a directly-downloaded .exe would.
DISK_IMAGE_EXTENSIONS = {"iso", "img", "vhd", "vhdx"}

MACRO_DOCUMENT_EXTENSIONS = {
    "docm", "xlsm", "pptm", "dotm", "xltm", "potm", "xlam", "ppam",
}

# Common, ordinary file types that show up in legitimate torrents and don't
# warrant even a baseline suspicion score from UnknownExtensionRule below --
# kept separate from MEDIA_EXTENSIONS since it also covers documents/archives
# that aren't "media" in the media_ratio sense used by build_context().
KNOWN_BENIGN_EXTENSIONS = {
    "txt", "pdf", "epub", "mobi", "azw", "azw3", "cbz", "cbr",
    "jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "tiff", "ico",
    "zip", "rar", "7z", "tar", "gz", "bz2", "xz",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "rtf",
    "csv", "json", "xml", "md", "log",
}

SUSPICIOUS_NAME_PATTERNS = [
    re.compile(r"\b(keygen|crack|activator|patch|loader|serial)\b", re.IGNORECASE),
]

# Unicode right-to-left override, classic technique to disguise a real
# extension (e.g. "gnp.exe" rendered reversed to look like "exe.png").
RTL_OVERRIDE = "‮"

# [.\s_-]+ (not a single literal dot) between the fake and real extension --
# a bare "\." was trivially defeated by padding the name with extra dots or
# spaces (e.g. "facture.pdf.................exe"), which still visually reads
# as a double extension but no longer matched a single-dot pattern.
DOUBLE_EXTENSION_RE = re.compile(
    r"\.[a-z0-9]{2,4}[.\s_-]+(" + "|".join(EXECUTABLE_EXTENSIONS) + r")$",
    re.IGNORECASE,
)

TINY_EXECUTABLE_SIZE_BYTES = 20 * 1024  # under this, a dropper-stub-sized exe is suspicious


@lru_cache(maxsize=4096)
def _extension(path: str) -> str:
    if "." not in path:
        return ""
    return path.rsplit(".", 1)[-1].lower()


@dataclass
class RuleHit:
    score_delta: int
    reason: str


@dataclass
class ScanContext:
    torrent_name: str
    media_ratio: float  # fraction of files in the torrent that look like media


class Rule(Protocol):
    def evaluate(self, file: FileEntry, context: ScanContext) -> RuleHit | None:
        ...


class DoubleExtensionRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> RuleHit | None:
        if DOUBLE_EXTENSION_RE.search(file.path):
            return RuleHit(60, "Double extension masque un exécutable (ex: .pdf.exe)")
        return None


class ExecutableExtensionRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> RuleHit | None:
        ext = _extension(file.path)
        if ext in EXECUTABLE_EXTENSIONS:
            # 35, not 25: this is the ONLY rule that fires for a normal-sized,
            # plainly-named executable with no other red flag -- at 25 it sat
            # structurally below the MEDIUM threshold (30), so a real
            # executable with an ordinary name/size was never flagged at all.
            return RuleHit(35, f"Extension exécutable ({ext})")
        return None


class DiskImageExtensionRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> RuleHit | None:
        ext = _extension(file.path)
        if ext in DISK_IMAGE_EXTENSIONS:
            return RuleHit(
                25,
                f"Image disque montable ({ext}) : contourne l'avertissement SmartScreen du téléchargement direct",
            )
        return None


class MacroDocumentExtensionRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> RuleHit | None:
        ext = _extension(file.path)
        if ext in MACRO_DOCUMENT_EXTENSIONS:
            return RuleHit(20, f"Document bureautique avec macros ({ext})")
        return None


class ExecutableFlagRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> RuleHit | None:
        ext = _extension(file.path)
        if file.executable_flag and ext not in EXECUTABLE_EXTENSIONS:
            return RuleHit(
                30,
                "Marqué exécutable au niveau du fichier/torrent (bit exécutable), sans extension exécutable reconnaissable",
            )
        return None


class MediaTorrentExecutableMismatchRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> RuleHit | None:
        ext = _extension(file.path)
        if ext in EXECUTABLE_EXTENSIONS and context.media_ratio >= 0.5:
            return RuleHit(20, "Exécutable inattendu dans un torrent principalement média")
        return None


class SuspiciousNameRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> RuleHit | None:
        if RTL_OVERRIDE in file.path:
            return RuleHit(70, "Caractère RTL-override détecté (extension probablement falsifiée)")
        for pattern in SUSPICIOUS_NAME_PATTERNS:
            if pattern.search(file.path):
                return RuleHit(30, "Nom de fichier évoquant un crack/keygen/activator")
        return None


class SizeAnomalyRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> RuleHit | None:
        ext = _extension(file.path)
        if ext in EXECUTABLE_EXTENSIONS and 0 < file.size < TINY_EXECUTABLE_SIZE_BYTES:
            return RuleHit(15, "Exécutable anormalement petit pour son type (possible dropper)")
        return None


class HiddenOrSuspiciousPathRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> RuleHit | None:
        if file.hidden:
            return RuleHit(20, "Fichier marqué caché dans le torrent")
        return None


_KNOWN_EXTENSIONS = (
    EXECUTABLE_EXTENSIONS | DISK_IMAGE_EXTENSIONS | MACRO_DOCUMENT_EXTENSIONS
    | MEDIA_EXTENSIONS | KNOWN_BENIGN_EXTENSIONS
)


class UnknownExtensionRule:
    """Every other rule here is extension-based, so a real executable simply
    renamed to an extension outside all the fixed lists above (e.g. .dat,
    .chm) previously scored exactly 0 -- invisible, no artifice required.
    This scanner runs on torrent metadata alone, before any bytes are on
    disk, so it structurally cannot sniff real file content (no magic-bytes
    check is possible here) -- this rule can only restore some VISIBILITY
    for an unrecognized extension, not certainty. Scored low enough (15) to
    stay well under MEDIUM on its own -- ordinary, harmless, uncommon file
    extensions (app-specific .cfg/.dat/.db files bundled in a torrent) are
    common and shouldn't be auto-flagged by this alone."""

    def evaluate(self, file: FileEntry, context: ScanContext) -> RuleHit | None:
        ext = _extension(file.path)
        if ext and ext not in _KNOWN_EXTENSIONS:
            return RuleHit(15, f"Extension inconnue ({ext}) : contenu non vérifiable avant téléchargement")
        return None


DEFAULT_RULES: list[Rule] = [
    DoubleExtensionRule(),
    ExecutableExtensionRule(),
    DiskImageExtensionRule(),
    MacroDocumentExtensionRule(),
    ExecutableFlagRule(),
    MediaTorrentExecutableMismatchRule(),
    SuspiciousNameRule(),
    SizeAnomalyRule(),
    HiddenOrSuspiciousPathRule(),
    UnknownExtensionRule(),
]


def build_context(torrent_name: str, files: list[FileEntry]) -> ScanContext:
    if not files:
        return ScanContext(torrent_name=torrent_name, media_ratio=0.0)
    media_count = sum(1 for f in files if _extension(f.path) in MEDIA_EXTENSIONS)
    return ScanContext(torrent_name=torrent_name, media_ratio=media_count / len(files))
