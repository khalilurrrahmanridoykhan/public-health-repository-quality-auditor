"""Maps this tool's own checks to the Digital Public Goods (DPG) Standard —
https://github.com/DPGAlliance/dpg-standard, indicator text quoted from
`standard.md` as of 2025-06-26 (v1.1.7, the file's own self-reported
version header is stale at v1.1.4 but the indicator table itself reflects
the 1.1.7 changelog entries, e.g. indicator 8's example text was removed
per https://github.com/DPGAlliance/dpg-standard/issues/200).

This is deliberately narrow: it maps indicators to signals this tool can
actually compute from repository content, and says so explicitly where it
can't. It never claims an indicator is "met" — only that an automated
check relevant to it found something, or found nothing, or that the
indicator needs the maintainer's own evidence because no repository-
content signal could ever establish it (SDG relevance, legal compliance,
content-moderation policy, etc. are organizational claims, not things a
static scan can verify).

Submitting to the DPG Registry is a decision for the maintainer to make
with the real evidence the Standard asks for — this is a pre-check, not
a substitute for the submission process.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import AuditReport

STATUS_CLEAN = "automated_check_clean"
STATUS_FLAGGED = "automated_check_flagged"
STATUS_NOT_AUTOMATABLE = "not_automatable"


@dataclass(frozen=True)
class DpgIndicatorResult:
    id: str
    title: str
    requirement: str
    status: str
    detail: str


def _check_passed(report: AuditReport, key: str) -> bool | None:
    result = next((item for item in report.results if item.key == key), None)
    return result.passed if result else None


def _dpg_2_open_license(report: AuditReport) -> DpgIndicatorResult:
    passed = _check_passed(report, "license")
    if passed is None:
        status, detail = STATUS_NOT_AUTOMATABLE, "The hygiene pack didn't run."
    elif passed:
        status, detail = (
            STATUS_CLEAN,
            "A LICENSE file is present. This does not confirm it's on the "
            "OSI-approved list the Standard requires — verify against "
            "https://opensource.org/licenses.",
        )
    else:
        status, detail = STATUS_FLAGGED, "No LICENSE file was found."
    return DpgIndicatorResult(
        "2",
        "Use of Approved Open Licenses",
        "Digital public goods must demonstrate the use of an approved "
        "open license (OSI-approved for software, Creative Commons for "
        "content, Open Data Commons for data).",
        status,
        detail,
    )


def _dpg_5_documentation(report: AuditReport) -> DpgIndicatorResult:
    keys = ("readme", "dependencies", "reproduction")
    checks = [_check_passed(report, key) for key in keys]
    if all(check is None for check in checks):
        status, detail = STATUS_NOT_AUTOMATABLE, "The hygiene pack didn't run."
    elif all(checks):
        status, detail = (
            STATUS_CLEAN,
            "README, dependency specification, and reproduction "
            "instructions are all present — the closest this tool gets to "
            "the Standard's \"a technical person unfamiliar with the "
            "project could launch and run it\" bar.",
        )
    else:
        failing = [key for key, check in zip(keys, checks) if check is False]
        status, detail = (
            STATUS_FLAGGED,
            f"Missing: {', '.join(failing)}.",
        )
    return DpgIndicatorResult(
        "5",
        "Documentation",
        "Digital public goods require documentation of the source code, "
        "use cases, and/or functional requirements — for software, "
        "technical documentation letting an unfamiliar technical person "
        "launch and run it.",
        status,
        detail,
    )


def _dpg_7_privacy_and_law(report: AuditReport) -> DpgIndicatorResult:
    passed = _check_passed(report, "privacy")
    if passed is None:
        status, detail = STATUS_NOT_AUTOMATABLE, "The hygiene pack didn't run."
    elif passed:
        status, detail = (
            STATUS_CLEAN,
            "The README mentions privacy/de-identification/sensitive-data "
            "terms. This is a keyword check, not a legal compliance "
            "review — it cannot establish adherence to privacy law.",
        )
    else:
        status, detail = (
            STATUS_FLAGGED,
            "No privacy-related language was found in the README at all.",
        )
    return DpgIndicatorResult(
        "7",
        "Adherence to Privacy and Applicable Laws",
        "Digital public goods must be designed and developed to comply "
        "with privacy and other applicable laws.",
        status,
        detail,
    )


def _dpg_8_standards_and_best_practices(report: AuditReport) -> DpgIndicatorResult:
    if report.has_blocking_findings:
        error_packs = sorted(
            {finding.pack for finding in report.findings if finding.severity == "error"}
        )
        status, detail = (
            STATUS_FLAGGED,
            f"Error-severity findings from: {', '.join(error_packs)}.",
        )
    else:
        status, detail = (
            STATUS_CLEAN,
            "No pack reported an error-severity finding. This reflects "
            "whichever packs actually ran (platform packs only activate on "
            "a matching marker file) — it is not a general best-practices "
            "certification.",
        )
    return DpgIndicatorResult(
        "8",
        "Adherence to Standards & Best Practices",
        "Digital public goods must be designed and developed to align "
        "with relevant standards, best practices, and/or principles.",
        status,
        detail,
    )


def _dpg_9a_data_privacy_and_security(report: AuditReport) -> DpgIndicatorResult:
    pii_findings = [finding for finding in report.findings if finding.pack == "pii"]
    if pii_findings:
        rule_ids = sorted({finding.rule_id for finding in pii_findings})
        status, detail = STATUS_FLAGGED, f"PII pack findings: {', '.join(rule_ids)}."
    else:
        status, detail = (
            STATUS_CLEAN,
            "The pii pack found no patient-data, committed-secret, or "
            "DB-dump findings. This is evidence of absence, not proof of "
            "the data-handling safeguards this indicator actually asks "
            "about — those need the maintainer's own documentation.",
        )
    return DpgIndicatorResult(
        "9a",
        "Data Privacy & Security",
        "Digital public goods that collect, store and distribute "
        "personally identifiable (PII) data must demonstrate how they "
        "ensure its privacy, security, and integrity.",
        status,
        detail,
    )


# Indicators with no repository-content signal this tool could ever
# compute — each `detail` says what a maintainer actually needs instead
# of leaving the indicator unexplained.
_NOT_AUTOMATABLE = (
    (
        "1",
        "Relevance to Sustainable Development Goals",
        "Digital public goods must demonstrate relevance to advancing the "
        "Sustainable Development Goals (SDGs).",
        "Requires the maintainer's own documented link to specific SDG "
        "targets/indicators — not something repository content alone "
        "establishes.",
    ),
    (
        "3",
        "Clear Ownership",
        "Ownership of assets the digital public good produces must be "
        "clearly defined and documented (copyright, trademark, or other "
        "public record).",
        "A CITATION.cff identifies authors, but authorship isn't the same "
        "claim as documented ownership — needs the maintainer's own "
        "evidence.",
    ),
    (
        "4",
        "Platform Independence",
        "Mandatory dependencies that create more restrictions than the "
        "project's own license must be shown to have open alternatives, "
        "or independence must be proven.",
        "Requires judgment about the project's actual dependency graph "
        "and licensing, not a pattern a static scan can evaluate.",
    ),
    (
        "6",
        "Mechanism for Extracting Data and Content",
        "Digital public goods with non-PII data must design for "
        "extracting/importing it in a non-proprietary format.",
        "A data_dictionary/provenance file describes data; it doesn't "
        "establish that an export mechanism exists.",
    ),
    (
        "9b",
        "Inappropriate & Illegal Content",
        "Digital public goods that collect, store, or distribute content "
        "must have policies and processes for detecting, moderating, and "
        "removing inappropriate/illegal content.",
        "A repository-content scan has no way to assess a project's "
        "moderation policies or processes.",
    ),
    (
        "9c",
        "Protection from Harassment",
        "Projects facilitating user/contributor interaction need a "
        "process protecting people from grief, abuse, and harassment, "
        "including systems addressing underage users' safety.",
        "A CODE_OF_CONDUCT.md existing doesn't establish that a working "
        "harassment-protection process exists — needs the maintainer's "
        "own evidence.",
    ),
)


def dpg_readiness(report: AuditReport) -> tuple[DpgIndicatorResult, ...]:
    """A best-effort reading of `report` against the DPG Standard's 9
    indicators (9 split into 9a/9b/9c), for a maintainer deciding whether
    they're ready to start a real DPG Registry submission — not a
    substitute for it. See the module docstring for the honesty policy
    behind each mapping.
    """
    automated = (
        _dpg_2_open_license(report),
        _dpg_5_documentation(report),
        _dpg_7_privacy_and_law(report),
        _dpg_8_standards_and_best_practices(report),
        _dpg_9a_data_privacy_and_security(report),
    )
    not_automatable = tuple(
        DpgIndicatorResult(id_, title, requirement, STATUS_NOT_AUTOMATABLE, detail)
        for id_, title, requirement, detail in _NOT_AUTOMATABLE
    )
    return tuple(
        sorted(automated + not_automatable, key=lambda result: result.id)
    )


_STATUS_ICON = {
    STATUS_CLEAN: "✅",
    STATUS_FLAGGED: "🛑",
    STATUS_NOT_AUTOMATABLE: "⚪",
}


def dpg_readiness_markdown(results: tuple[DpgIndicatorResult, ...]) -> str:
    lines = [
        "## DPG Standard readiness (pre-check, not a submission)",
        "",
        "Maps this audit to the "
        "[Digital Public Goods Standard](https://github.com/DPGAlliance/dpg-standard)'s "
        "9 indicators. ✅ an automated check relevant to this indicator found "
        "nothing · 🛑 one found something · ⚪ no repository-content signal "
        "exists for this indicator at all — it needs the maintainer's own "
        "evidence. **This is not a certification and does not replace the "
        "real DPG Registry submission process.**",
        "",
        "| # | Indicator | Status | Detail |",
        "| :-- | :--- | :--: | :--- |",
    ]
    for result in results:
        icon = _STATUS_ICON[result.status]
        lines.append(f"| {result.id} | {result.title} | {icon} | {result.detail} |")
    return "\n".join(lines)
