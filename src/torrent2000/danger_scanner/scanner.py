from torrent2000.danger_scanner.models import FileEntry, FileRisk, RiskLevel, ScanResult
from torrent2000.danger_scanner.rules import DEFAULT_RULES, Rule, build_context

MAX_SCORE_PER_FILE = 100

_LEVEL_THRESHOLDS = (
    (80, RiskLevel.CRITICAL),
    (55, RiskLevel.HIGH),
    (30, RiskLevel.MEDIUM),
    (10, RiskLevel.LOW),
)


def _score_to_level(score: int) -> RiskLevel:
    for threshold, level in _LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return RiskLevel.SAFE


def scan_files(
    files: list[FileEntry],
    torrent_name: str = "",
    rules: list[Rule] | None = None,
) -> ScanResult:
    rules = rules if rules is not None else DEFAULT_RULES
    context = build_context(torrent_name, files)

    file_risks: list[FileRisk] = []
    flagged_indices: list[int] = []
    overall_score = 0

    for file in files:
        score = 0
        reasons: list[str] = []
        for rule in rules:
            hit = rule.evaluate(file, context)
            if hit is not None:
                score += hit.score_delta
                reasons.append(hit.reason)
        score = min(score, MAX_SCORE_PER_FILE)
        level = _score_to_level(score)
        file_risks.append(FileRisk(file=file, score=score, level=level, reasons=reasons))
        if level >= RiskLevel.MEDIUM:
            flagged_indices.append(file.index)
        overall_score = max(overall_score, score)

    return ScanResult(file_risks=file_risks, overall_score=overall_score, flagged_indices=flagged_indices)
