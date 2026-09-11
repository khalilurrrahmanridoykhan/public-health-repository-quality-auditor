from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from ..models import AuditPolicy, Finding


class RepoView:
    """Normalised, ignore-path-filtered view of a repository's files.

    Shared by every pack so path handling (trimming, lower-casing, honouring
    `.ph-repo-auditor.yml`'s `ignore_paths`) happens exactly once.
    """

    def __init__(
        self, files: Mapping[str, str | None], ignore_paths: tuple[str, ...] = ()
    ):
        self.ignore_paths = ignore_paths
        cleaned: dict[str, str | None] = {}
        for path, content in files.items():
            key = path.strip("/").lower()
            if any(
                key == prefix or key.startswith(f"{prefix}/")
                for prefix in ignore_paths
            ):
                continue
            cleaned[key] = content
        self.files: dict[str, str | None] = cleaned
        self.paths: frozenset[str] = frozenset(cleaned)

    def find(self, names: set[str]) -> tuple[str, ...]:
        """Repo-relative paths whose final path segment is one of `names`."""
        return tuple(
            sorted(path for path in self.paths if path.rsplit("/", 1)[-1] in names)
        )

    def with_prefix(self, prefixes: tuple[str, ...]) -> tuple[str, ...]:
        """Repo-relative paths starting with any of `prefixes`."""
        return tuple(sorted(path for path in self.paths if path.startswith(prefixes)))

    def text(self, *names: str) -> str:
        """Lower-cased content of the first present file among `names`, or ''."""
        for name in names:
            content = self.files.get(name)
            if content:
                return content.lower()
        return ""

    def anchor(self) -> str | None:
        """A representative tracked file to anchor repo-wide findings to.

        Used for GitHub Check Run annotations and SARIF locations when a
        finding (e.g. "no README") has no single offending line.
        """
        for name in ("readme.md", "readme.rst"):
            if name in self.files:
                return name
        return min(self.paths) if self.paths else None


@runtime_checkable
class Pack(Protocol):
    id: str

    def detect(self, repo: RepoView) -> float:
        """Confidence in [0, 1] that this pack applies to `repo`.

        The hygiene pack always returns 1.0; platform packs (FHIR, DHIS2,
        OpenMRS, ...) look for marker files and return 0.0 when absent.
        """
        ...

    def run(self, repo: RepoView, policy: AuditPolicy) -> list[Finding]:
        """Findings for `repo`. Only called when `detect()` clears the
        registry's selection threshold."""
        ...
