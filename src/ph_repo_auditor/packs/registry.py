from __future__ import annotations

from .base import Pack, RepoView
from .dhis2 import Dhis2Pack
from .fhir import FhirPack
from .hygiene import HygienePack
from .migration_safety import MigrationSafetyPack
from .openmrs import OpenmrsPack
from .pii import PiiPack
from .portability import PortabilityPack
from .rulepacks import load_rulepacks

DEFAULT_PACKS: tuple[Pack, ...] = (
    HygienePack(),
    FhirPack(),
    Dhis2Pack(),
    OpenmrsPack(),
    PiiPack(),
    MigrationSafetyPack(),
    PortabilityPack(),
)


class PackRegistry:
    """Selects which registered packs apply to a given repository.

    Phase 1 shipped `hygiene`; Phase 2 added `fhir`; Phase 3 added `dhis2`;
    Phase 4 added `openmrs`; Phase 5 added the cross-cutting `pii`,
    `migration-safety`, and `portability` packs, which (unlike the platform
    packs) always detect at confidence 1.0 — they apply to any repository,
    not just ones matching a specific platform. Phase 7 added
    `include_rulepacks`: every `*.yml`/`*.yaml` file bundled under
    `ph_repo_auditor/rulepacks/` is loaded as its own pack, with no change
    to this file needed when a new rulepack is added. Later phases
    register more built-in packs here without touching callers.
    """

    def __init__(
        self,
        packs: tuple[Pack, ...] = DEFAULT_PACKS,
        *,
        include_rulepacks: bool = True,
    ):
        self.rulepack_warnings: tuple[str, ...] = ()
        if include_rulepacks:
            rulepacks, warnings = load_rulepacks()
            self.rulepack_warnings = tuple(warnings)
            packs = packs + tuple(rulepacks)
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
