from __future__ import annotations

from .base import Pack, RepoView
from .dhis2 import Dhis2Pack
from .fhir import FhirPack
from .hygiene import HygienePack
from .openmrs import OpenmrsPack

DEFAULT_PACKS: tuple[Pack, ...] = (HygienePack(), FhirPack(), Dhis2Pack(), OpenmrsPack())


class PackRegistry:
    """Selects which registered packs apply to a given repository.

    Phase 1 shipped `hygiene`; Phase 2 added `fhir`; Phase 3 added `dhis2`;
    Phase 4 added `openmrs`. Later phases register more here without
    touching callers.
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
