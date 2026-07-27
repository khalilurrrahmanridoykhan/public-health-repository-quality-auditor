from dataclasses import dataclass, field


@dataclass(frozen=True)
class CheckResult:
    key: str
    title: str
    passed: bool
    points: int
    recommendation: str
    evidence: tuple[str, ...] = ()


@dataclass
class AuditReport:
    repository: str
    results: list[CheckResult] = field(default_factory=list)

    @property
    def score(self) -> int:
        earned = sum(item.points for item in self.results if item.passed)
        possible = sum(item.points for item in self.results)
        return round(earned / possible * 100) if possible else 0

    @property
    def grade(self) -> str:
        if self.score >= 90:
            return "A"
        if self.score >= 80:
            return "B"
        if self.score >= 70:
            return "C"
        if self.score >= 60:
            return "D"
        return "F"

    def to_dict(self) -> dict:
        return {
            "repository": self.repository,
            "score": self.score,
            "grade": self.grade,
            "checks": [
                {
                    "key": item.key,
                    "title": item.title,
                    "passed": item.passed,
                    "points": item.points,
                    "recommendation": item.recommendation,
                    "evidence": list(item.evidence),
                }
                for item in self.results
            ],
        }

    def to_markdown(self) -> str:
        rows = ["| Check | Result | Points |", "|---|---:|---:|"]
        for item in self.results:
            status = "✅ Pass" if item.passed else "❌ Needs work"
            earned = item.points if item.passed else 0
            rows.append(f"| {item.title} | {status} | {earned}/{item.points} |")

        recommendations = [
            f"- **{item.title}:** {item.recommendation}"
            for item in self.results
            if not item.passed
        ]
        if not recommendations:
            recommendations = ["- All configured quality checks passed."]

        return "\n".join(
            [
                f"## Public Health Repository Quality: {self.score}/100 ({self.grade})",
                "",
                *rows,
                "",
                "### Recommended next steps",
                "",
                *recommendations,
                "",
                "_This automated review supports maintainers; it does not certify scientific validity, privacy compliance, or research ethics._",
            ]
        )
