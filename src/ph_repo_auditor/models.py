from dataclasses import dataclass, field


CHECK_KEYS = (
    "readme",
    "license",
    "citation",
    "dependencies",
    "reproduction",
    "tests",
    "data_dictionary",
    "provenance",
    "privacy",
    "ethics",
)


@dataclass(frozen=True)
class AuditPolicy:
    minimum_score: int = 80
    disabled_checks: tuple[str, ...] = ()
    required_files: tuple[str, ...] = ()
    ignore_paths: tuple[str, ...] = ()
    privacy_terms: tuple[str, ...] = (
        "privacy",
        "de-ident",
        "anonym",
        "patient",
        "person-level",
        "sensitive data",
    )


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
    minimum_score: int = 80
    missing_required_files: tuple[str, ...] = ()
    policy_warnings: tuple[str, ...] = ()

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

    @property
    def passed(self) -> bool:
        return (
            self.score >= self.minimum_score
            and not self.missing_required_files
            and not self.policy_warnings
        )

    def to_dict(self) -> dict:
        return {
            "repository": self.repository,
            "score": self.score,
            "grade": self.grade,
            "passed": self.passed,
            "minimum_score": self.minimum_score,
            "missing_required_files": list(self.missing_required_files),
            "policy_warnings": list(self.policy_warnings),
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
                f"Policy threshold: **{self.minimum_score}/100** · Result: **{'Pass' if self.passed else 'Needs work'}**",
                "",
                *rows,
                "",
                "### Required files",
                "",
                *(
                    [f"- Missing required file: `{path}`" for path in self.missing_required_files]
                    or ["- All configured required files are present."]
                ),
                "",
                "### Recommended next steps",
                "",
                *recommendations,
                *(
                    [
                        "",
                        "### Policy warnings",
                        "",
                        *[f"- {warning}" for warning in self.policy_warnings],
                    ]
                    if self.policy_warnings
                    else []
                ),
                "",
                "_This automated review supports maintainers; it does not certify scientific validity, privacy compliance, or research ethics._",
            ]
        )
