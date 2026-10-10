# Proposal: phase3.3_procedural-families

## Why
Painter's generators, filters, grunges and materials are Substance (`.sbsar`) graphs run by Adobe's proprietary engine, which UzPainter will not link, bundle or execute (decision 002, `docs/licensing-and-clean-room.md`). MAT-02, MAT-03, MAT-04, ARC-05, RES-04 and CLR-01…CLR-06 (`docs/prd.md`) require the procedurals used by delivered and locked recipes to evaluate identically through UzPainter's own clean-room implementations or per-project frozen snapshots, behind a backend seam with per-asset parity status and no silent substitution. This is DAG node P3-PROC (`docs/dag.md`), implementing D4 in `docs/architecture/05-procedural-content.md`. It bundles a seam, a snapshot backend and several independently certified families, so under the DAG task decomposition rule it is split into child tasks; this parent is the integration and acceptance task.

## What Changes
- Integrates the children into the procedural subsystem: `IProceduralBackend` with `SnapshotBackend` and `HlslBackend`, the certified resource families (mesh-map generators, filters, grunges and noises, materials), parity status per asset and the asset library with provenance (`05-procedural-content.md` §2–§6).
- Publishes the Tier 2a report (`docs/architecture/14-parity-testing.md` §3) under `parity/reports/phase3/`: every certified asset × 3 meshes × {1024, 2048, 4096} × parameter sets × seeds, numbers and hashes only, exceptions relied on listed.
- Regenerates the capability manifest: certified assets `supported`, every other Painter procedural and arbitrary `.sbsar` execution listed as release gaps (`05-procedural-content.md` §5).

## Dependencies
- DAG inputs: `phase0.6_procedural-feasibility` (P0-FEAS-PROC go/no-go and first residuals), `phase2.10_pilot-tunic-recovery` (P2-TUNIC).
- Mandatory children: `phase3.1_proc-backend-seam`, `phase3.2_proc-snapshot-backend`, `phase3.2_proc-generator-families`, `phase3.2_proc-grunge-families`, `phase3.2_proc-filter-families`, `phase3.2_proc-material-families`.
- Downstream (DAG): `phase3.6_smart-presets-projections` (P3-SMART).

## Acceptance
DAG gate for P3-PROC: Tier 2a published. A calibrated (non-zero residual) asset passes only through an owner-approved, versioned exception (decision 017); without one it is a failure. The parent closes only when all mandatory children pass.

## Impact
- Affected specs: procedural
- Affected code: procedural backend seam, `HlslBackend` kernels on the render core, `SnapshotBackend`, asset library and `uzpainter assets` CLI, `SourceSubstance` facade, capability manifest
- Breaking change: NO
- User benefit: the procedurals the Assets3D recipes use, evaluated without Adobe's runtime and with visible parity status
