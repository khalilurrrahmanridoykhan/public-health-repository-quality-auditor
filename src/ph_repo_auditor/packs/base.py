from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from ..models import AuditPolicy, Finding


class RepoView:
    """A repository's files, honouring `.ph-repo-auditor.yml`'s `ignore_paths`.

    Paths keep their real, original case — a `Finding.file` has to be an
    actual path GitHub will resolve for an annotation or a SARIF location, and
    most of what packs beyond hygiene look at (`App.tsx`,
    `StructureDefinition-Foo.json`) is case-sensitive by convention. Filename
    *matching* (`find`, `with_prefix`, `text`, `anchor`) is still
    case-insensitive, matching on a lower-cased comparison and handing back
    the real path — pass already-lower-cased names/prefixes to them.
    """

    def __init__(
        self, files: Mapping[str, str | None], ignore_paths: tuple[str, ...] = ()
    ):
        self.ignore_paths = ignore_paths
        cleaned: dict[str, str | None] = {}
        for path, content in files.items():
            key = path.strip("/")
            lowered = key.lower()
            if any(
                lowered == prefix or lowered.startswith(f"{prefix}/")
                for prefix in ignore_paths
            ):
                continue
            cleaned[key] = content
        self.files: dict[str, str | None] = cleaned
        self.paths: frozenset[str] = frozenset(cleaned)
        self.paths_lower: frozenset[str] = frozenset(path.lower() for path in cleaned)
        # First path seen wins on a same-directory case collision (rare).
        self._lower_to_path: dict[str, str] = {}
        for path in cleaned:
            self._lower_to_path.setdefault(path.lower(), path)

    def find(self, names: set[str]) -> tuple[str, ...]:
        """Real-case paths whose final path segment matches one of `names`
        (already lower-case) case-insensitively."""
        return tuple(
            sorted(
                path
                for path in self.paths
                if path.rsplit("/", 1)[-1].lower() in names
            )
        )

    def with_prefix(self, prefixes: tuple[str, ...]) -> tuple[str, ...]:
        """Real-case paths starting with any of `prefixes` (already
        lower-case) case-insensitively."""
        return tuple(
            sorted(path for path in self.paths if path.lower().startswith(prefixes))
        )

    def text(self, *names: str) -> str:
        """Lower-cased content of the first present file among `names`
        (already lower-case exact paths), matched case-insensitively, or ''."""
        for name in names:
            path = self._lower_to_path.get(name)
            content = self.files.get(path) if path else None
            if content:
                return content.lower()
        return ""

    def get(self, path: str) -> str | None:
        """Content of `path`, matched case-insensitively, or None."""
        return self.files.get(self._lower_to_path.get(path.lower(), ""))

    def anchor(self) -> str | None:
        """A representative tracked file to anchor repo-wide findings to.

        Used for GitHub Check Run annotations and SARIF locations when a
        finding (e.g. "no README") has no single offending line.
        """
        for name in ("readme.md", "readme.rst"):
            path = self._lower_to_path.get(name)
            if path:
                return path
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
