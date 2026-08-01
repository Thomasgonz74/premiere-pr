import re
from dataclasses import dataclass
from typing import Optional, Protocol

from torrent2000.danger_scanner.models import FileEntry

EXECUTABLE_EXTENSIONS = {
    "exe", "bat", "cmd", "com", "js", "jse", "vbs", "vbe", "wsf", "wsh",
    "ps1", "jar", "scr", "pif", "msi", "lnk", "hta", "cpl", "gadget", "reg",
}

MEDIA_EXTENSIONS = {
    "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "mp3", "flac", "wav",
    "aac", "ogg", "m4a", "srt", "sub", "idx", "nfo",
}

SUSPICIOUS_NAME_PATTERNS = [
    re.compile(r"\b(keygen|crack|activator|patch|loader|serial)\b", re.IGNORECASE),
]

# Unicode right-to-left override, classic technique to disguise a real
# extension (e.g. "gnp.exe" rendered reversed to look like "exe.png").
RTL_OVERRIDE = "‮"

DOUBLE_EXTENSION_RE = re.compile(
    r"\.[a-z0-9]{2,4}\.(" + "|".join(EXECUTABLE_EXTENSIONS) + r")$",
    re.IGNORECASE,
)

TINY_EXECUTABLE_SIZE_BYTES = 20 * 1024  # under this, a dropper-stub-sized exe is suspicious


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
    def evaluate(self, file: FileEntry, context: ScanContext) -> Optional[RuleHit]:
        ...


class DoubleExtensionRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> Optional[RuleHit]:
        if DOUBLE_EXTENSION_RE.search(file.path):
            return RuleHit(60, "Double extension masque un exécutable (ex: .pdf.exe)")
        return None


class ExecutableExtensionRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> Optional[RuleHit]:
        ext = _extension(file.path)
        if ext in EXECUTABLE_EXTENSIONS:
            return RuleHit(25, f"Extension exécutable ({ext})")
        return None


class MediaTorrentExecutableMismatchRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> Optional[RuleHit]:
        ext = _extension(file.path)
        if ext in EXECUTABLE_EXTENSIONS and context.media_ratio >= 0.5:
            return RuleHit(20, "Exécutable inattendu dans un torrent principalement média")
        return None


class SuspiciousNameRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> Optional[RuleHit]:
        if RTL_OVERRIDE in file.path:
            return RuleHit(70, "Caractère RTL-override détecté (extension probablement falsifiée)")
        for pattern in SUSPICIOUS_NAME_PATTERNS:
            if pattern.search(file.path):
                return RuleHit(30, "Nom de fichier évoquant un crack/keygen/activator")
        return None


class SizeAnomalyRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> Optional[RuleHit]:
        ext = _extension(file.path)
        if ext in EXECUTABLE_EXTENSIONS and 0 < file.size < TINY_EXECUTABLE_SIZE_BYTES:
            return RuleHit(15, "Exécutable anormalement petit pour son type (possible dropper)")
        return None


class HiddenOrSuspiciousPathRule:
    def evaluate(self, file: FileEntry, context: ScanContext) -> Optional[RuleHit]:
        if file.hidden:
            return RuleHit(20, "Fichier marqué caché dans le torrent")
        return None


DEFAULT_RULES: list[Rule] = [
    DoubleExtensionRule(),
    ExecutableExtensionRule(),
    MediaTorrentExecutableMismatchRule(),
    SuspiciousNameRule(),
    SizeAnomalyRule(),
    HiddenOrSuspiciousPathRule(),
]


def build_context(torrent_name: str, files: list[FileEntry]) -> ScanContext:
    if not files:
        return ScanContext(torrent_name=torrent_name, media_ratio=0.0)
    media_count = sum(1 for f in files if _extension(f.path) in MEDIA_EXTENSIONS)
    return ScanContext(torrent_name=torrent_name, media_ratio=media_count / len(files))
