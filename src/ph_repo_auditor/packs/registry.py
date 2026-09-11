from __future__ import annotations

from .base import Pack, RepoView
from .fhir import FhirPack
from .hygiene import HygienePack

DEFAULT_PACKS: tuple[Pack, ...] = (HygienePack(), FhirPack())


class PackRegistry:
    """Selects which registered packs apply to a given repository.

    Phase 1 ships a single pack (`hygiene`). Later phases register more
    (`fhir`, `dhis2`, `openmrs`, ...) here without touching callers.
    """

    def __init__(self, packs: tuple[Pack, ...] = DEFAULT_PACKS):
        self.packs = packs

    def select(
        self, repo: RepoView, requested: tuple[str, ...] | None = None
    ) -> tuple[Pack, ...]:
        candidates = self.packs
        if requested:
            known = {pack.id for pack in self.packs}
            unknown = [pack_id for pack_id in requested if pack_id not in known]
            if unknown:
                raise ValueError(f"Unknown pack id(s): {', '.join(unknown)}")
            candidates = tuple(pack for pack in self.packs if pack.id in requested)
        return tuple(pack for pack in candidates if pack.detect(repo) > 0)
