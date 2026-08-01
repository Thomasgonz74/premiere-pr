from dataclasses import dataclass, field
from enum import IntEnum


class RiskLevel(IntEnum):
    SAFE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass(frozen=True)
class FileEntry:
    index: int
    path: str
    size: int
    hidden: bool = False
    executable_flag: bool = False


@dataclass
class FileRisk:
    file: FileEntry
    score: int
    level: RiskLevel
    reasons: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    file_risks: list[FileRisk]
    overall_score: int
    flagged_indices: list[int]

    def risk_for_index(self, index: int) -> "FileRisk | None":
        for fr in self.file_risks:
            if fr.file.index == index:
                return fr
        return None
