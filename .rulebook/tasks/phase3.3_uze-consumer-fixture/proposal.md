# Proposal: phase3.3_uze-consumer-fixture

## Why
ARC-06 (`docs/prd.md`) requires the UzEngine preset to be validated by an external UzEngine consumer fixture; EXP-08 names that fixture as the preset's acceptance; OWN-02 and decision 021 (Q8) forbid any build or run-time dependency on UzEngine, so the engine runs only as an external executable on a test scene, like the Unreal and Blender fixtures. Decision 023 (Q10) requires gaps such as SpecularWeight to be reported, never compensated. Child of P3-UZE (`phase3.4_uzengine-preset`), implementing D7: `docs/architecture/08-export.md` §5.1 row 9 (bindings of the UzEngine preset table; decoded `.uztexture` compared with canonical maps under the lossy-derivative contract); `docs/architecture/07-preview-and-render-parity.md` §1 (whatever window or session the executable needs belongs to the fixture, not to UzPainter's no-window acceptance, NFR-01); `docs/architecture/13-engine-integration.md` §2.4 and `docs/architecture/12-mesh-import.md` §1 (the fixture loads its test mesh through a route UzEngine has qualified, never the defective glTF cook, and records which); `docs/architecture/14-parity-testing.md` §4 and §7 (lossy-derivative contract; external consumer fixtures run locally on the owner's machine, decision 028).

## What Changes
- **Fixture manifest** `parity/manifests/consumers/uzengine/wand-v1.json`: UzEngine executable identity (version, commit hash, SHA-256 of the executable), test scene, qualified mesh route, pinned published generation, expected bindings per slot (UzEngine preset table).
- **Runner**, run locally on the owner's machine (decision 028; the local run report is the evidence): invokes UzEngine's own executable as an external process on the published generation through the generation-pinning delivery adapter (`08-export.md` §5); UzPainter's build contains no UzEngine path, library or header beyond the vendored format definition.
- **Load-and-render check**: the scene loads `<set>.uzmat` and every `.uztexture`, renders a frame, and the fixture verifies each slot binding (albedo, normal, ORM, emissive, height) from the engine's own load report.
- **Normal convention check**: the exported normal convention matches the one settled by the Phase 0 normal fixture when shaded in UzEngine.
- **Lossy-derivative comparison**: decoded `.uztexture` levels against the canonical maps, reported as compression error, separate from authoring equality.
- **Gap report** in `parity/reports/phase3/`: SpecularWeight (no slot), SM5 opacity route, any binding the engine rejects, the mesh route used.
- **Defect detection**: a deliberately mis-bound `.uzmat` and a swapped colour space are caught by the fixture.

## Dependencies
- DAG input (through the parent): `phase2.10_pilot-tunic-recovery`.
- Previous child: `phase3.2_uze-uzmat-preset`.
- Delivered upstream and used here: `phase0.5_private-oracle-store` (private oracle store on the owner's machine, where the fixture runs locally, decision 028), `phase0.9_normal-convention-fixture`.
- Parent: `phase3.4_uzengine-preset`. The hat v8 run of row 9 belongs to `phase4.2_coverage-hat-v8`.

## Acceptance
Carries the P3-UZE gate evidence: the preset loads and renders in the external UzEngine fixture; gaps listed. Accepted when consumer-matrix row 9 passes on wand v1 with the expected bindings, the lossy-derivative numbers and the gap report are published, the defect-detection cases fail as intended, and an unavailable UzEngine executable fails the fixture explicitly instead of passing.

## Impact
- Affected specs: `export` (UzEngine consumer fixture)
- Affected code: `parity/manifests/consumers/uzengine/`; fixture runner run locally on the owner's machine (decision 028); `parity/reports/phase3/`
- Breaking change: NO
- User benefit: proof, from UzEngine's own executable, that UzPainter's UzEngine delivery loads and renders as specified
