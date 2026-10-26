# Procedural — backend seam, asset library and certification harness

## ADDED Requirements

### Requirement: No Silent Procedural Substitution
The procedural seam SHALL try `SnapshotBackend` then `HlslBackend` per asset and MUST raise `UnsupportedProcedural{asset, reason}` before any mutation when no backend can serve the request; it MUST NOT substitute a visually similar asset.

#### Scenario: Uncertified asset
Given a fill effect referencing a Painter generator that has no snapshot and no certified family
When the effect is inserted
Then `UnsupportedProcedural` MUST be raised, the revision MUST NOT advance and no other asset MUST be evaluated in its place

#### Scenario: Sbsar import
Given an arbitrary `.sbsar` file
When it is imported as a project resource
Then the import MUST raise `UnsupportedProcedural` with reason "no runtime"

### Requirement: Pinned Procedural Asset Versions
Procedural assets SHALL be project resources `uzasset://<family>/<id>@<version>` whose version is pinned in the project, and reopening MUST reproduce identical evaluation.

#### Scenario: Reopen
Given a saved project using `uzasset://grunge/<id>@1`
When it is reopened and exported
Then the export MUST be byte-identical to the export before saving

### Requirement: Internal Compatibility Aliases
Painter asset names SHALL exist only in an internal alias table used by `resource.search`; shipped assets MUST carry UzPainter names and provenance records.

#### Scenario: Alias lookup
Given a script calling `resource.search` with a Painter asset name that maps to a certified family
When the search runs
Then the result MUST be the UzPainter asset with its UzPainter name and provenance, resolved through the alias table

### Requirement: SourceSubstance Documented Semantics
The `SourceSubstance` facade SHALL follow the documented semantics of parameters, presets, image inputs, outputs and `ResolutionOverride` (power of two in [128, 4096]; `Auto` follows the texture-set resolution; raises for sources used by a Filter effect), and a missing or invalid mesh map MUST fail evaluation loudly.

#### Scenario: Invalid resolution override
Given a procedural source
When `resolution` is set to a non-power-of-two value
Then the call MUST raise as the documentation states and the source MUST be unchanged

### Requirement: Tier 2a Certification Harness
The certification harness SHALL evaluate each asset over 3 meshes × {1024, 2048, 4096} × parameter sets × seeds, report max/mean/p99 |Δ| and affected-texel counts, treat any non-zero residual as a candidate exception and never as a pass, and report a missing oracle blob as `oracle_unavailable`.

#### Scenario: Missing oracle blob
Given a manifest whose golden blob is absent from `UZP_PARITY_STORE`
When the harness runs
Then the comparison MUST fail as `oracle_unavailable`

### Requirement: Snapshot-Backed Filter Observations
Decision 363's closed contract in `docs/filter-observations-v2.md` SHALL govern the V2 observation namespace. V1 bytes and snapshot schemas /1-/3 MUST remain compatible. V2 SHALL retain the real snapshot host and original empty Paint, preserve the complete typed project projection and authoritative inventory, and expose only recorded Filter parameters, resource identity and image outputs. It MUST NOT admit Filter execution.

#### Scenario: Historical observation becomes stale
Given a valid V2 entry and a later project edit
When the project is saved and reopened
Then historical structural validation MUST remain independent of current bytes, while a getter MUST refuse unless one authoritative current inventory and the same project exactly match the recorded context

#### Scenario: Frozen raster is not a readout fixed point
Given an authenticated host raster containing negative zero or positive 2^-26
When the diagnostic importer runs the actual native transport and full-chain proof
Then raw upload MUST preserve the original bits, but frozen migration MUST refuse the non-fixed samples without normalizing the raster or mutating the destination

#### Scenario: Real evidence is incomplete
Given complete authored software tests but missing fresh F context or trusted native proof
When real V2 import is attempted
Then import MUST refuse, old expected values MUST NOT supply constructor inputs, and Filter parity or capability promotion MUST remain unaccepted
