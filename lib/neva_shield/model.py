"""Findings, scoring, and grading for Neva Shield. Python standard library only."""
from dataclasses import asdict, dataclass, field

from .redact import redact

SEVERITIES = ("critical", "high", "medium", "low")
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
WEIGHTS = {"critical": 30, "high": 15, "medium": 6, "low": 2}
GRADE_BANDS = ((90, "A"), (75, "B"), (60, "C"), (40, "D"))
NO_GRADE = "N/A"
# A scan that skipped a whole harness location cannot vouch for it, whatever else it found.
PARTIAL_SCORE_CAP = 89


@dataclass(frozen=True)
class Finding:
    """One rule hit. Rules name the key or field, and known credential shapes are redacted here."""

    rule_id: str
    severity: str
    path: str
    line: int
    message: str
    fix: str

    def __post_init__(self):
        for name in ("rule_id", "severity", "path", "message", "fix"):
            object.__setattr__(self, name, redact(getattr(self, name)))

    @property
    def key(self):
        return (self.path, self.line, self.rule_id)

    @property
    def scored(self):
        """LINK002 notes a link Shield did not read. It is not a defect to grade."""
        return self.rule_id != "LINK002"

    def as_dict(self):
        return asdict(self)


@dataclass
class ScanResult:
    root: str
    findings: list = field(default_factory=list)
    files_scanned: int = 0
    suppressed: int = 0
    skipped_targets: int = 0

    def __post_init__(self):
        self.root = redact(self.root)

    @property
    def empty(self):
        """Nothing was read, so there is nothing to grade. That is never a clean result."""
        return self.files_scanned == 0 and not any(
            item.scored and not item.rule_id.startswith("LINK") for item in self.findings)

    @property
    def score(self):
        if self.empty:
            return None
        score = max(0, 100 - sum(WEIGHTS[item.severity] for item in self.findings if item.scored))
        return min(score, PARTIAL_SCORE_CAP) if self.skipped_targets else score

    @property
    def grade(self):
        if self.empty:
            return NO_GRADE
        score = self.score
        for floor, letter in GRADE_BANDS:
            if score >= floor:
                return letter
        return "F"

    def counts(self):
        return {name: sum(1 for item in self.findings if item.severity == name) for name in SEVERITIES}

    def worst_rank(self):
        return max([SEVERITY_RANK[item.severity] for item in self.findings], default=-1)

    def as_dict(self):
        return {
            "tool": "neva-shield",
            "root": self.root,
            "grade": self.grade,
            "score": self.score,
            "files_scanned": self.files_scanned,
            "suppressed": self.suppressed,
            "skipped_targets": self.skipped_targets,
            "counts": self.counts(),
            "findings": [item.as_dict() for item in self.findings],
        }


def merge(root, results):
    """Combine several scans into one result, deduplicating by path, line, and rule."""
    unique = {}
    files = 0
    suppressed = 0
    skipped = 0
    for result in results:
        files += result.files_scanned
        suppressed += result.suppressed
        skipped += result.skipped_targets
        for item in result.findings:
            unique.setdefault(item.key, item)
    ordered = sorted(unique.values(), key=lambda item: (-SEVERITY_RANK[item.severity], item.path, item.line, item.rule_id))
    return ScanResult(root=root, findings=ordered, files_scanned=files, suppressed=suppressed, skipped_targets=skipped)
