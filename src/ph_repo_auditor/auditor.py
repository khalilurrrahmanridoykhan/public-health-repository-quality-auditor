from collections.abc import Mapping

from .models import AuditPolicy, AuditReport, CheckResult, Finding, PackScore
from .packs import PackRegistry, RepoView
from .packs.hygiene import findings_for


def audit_repository(
    repository: str,
    files: Mapping[str, str | None],
    policy: AuditPolicy | None = None,
    policy_warnings: tuple[str, ...] = (),
    packs: tuple[str, ...] | None = None,
    registry: PackRegistry | None = None,
) -> AuditReport:
    policy = policy or AuditPolicy()
    registry = registry or PackRegistry()
    repo = RepoView(files, policy.ignore_paths)
    active = tuple(
        pack
        for pack in registry.select(repo, packs)
        if pack.id not in policy.disabled_packs
    )
    active_ids = {pack.id for pack in active}

    # Hygiene stays the point-scored pack that drives `score`/`grade`/`passed`;
    # later packs (fhir, dhis2, ...) contribute findings and their own
    # `PackScore` without being averaged into the hygiene score.
    results: list[CheckResult] = []
    findings: list[Finding] = []
    pack_scores: list[PackScore] = []

    if "hygiene" in active_ids:
        hygiene = next(pack for pack in active if pack.id == "hygiene")
        results = hygiene.checks(repo, policy)
        findings.extend(findings_for(repo, results))
        earned = sum(result.points for result in results if result.passed)
        possible = sum(result.points for result in results)
        pack_scores.append(
            PackScore(
                "hygiene",
                round(earned / possible * 100) if possible else 0,
                earned,
                possible,
            )
        )

    for pack in active:
        if pack.id == "hygiene":
            continue
        findings.extend(pack.run(repo, policy))

    missing_required_files = tuple(
        path for path in policy.required_files if path not in repo.paths
    )
    return AuditReport(
        repository=repository,
        results=results,
        minimum_score=policy.minimum_score,
        missing_required_files=missing_required_files,
        policy_warnings=policy_warnings,
        findings=tuple(findings),
        pack_scores=tuple(pack_scores),
    )
