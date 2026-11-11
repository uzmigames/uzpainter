# Proposal: phase3.2_proc-material-families

## Why
MAT-03 and MAT-04 require the materials used by locked and delivered recipes (the locked bracer's leather family among them) to evaluate identically through UzPainter's own certified implementations (`docs/prd.md`, decision 002); PRJ-07 requires physical units to be preserved. The materials family (felt, leather grain, burlap, leather pattern) is listed in `docs/architecture/05-procedural-content.md` §3 (D4). This child of P3-PROC (`phase3.3_procedural-families`) is split out beyond the DAG rule's examples because materials are multi-output assets driven by physical size and are certified independently of grunges and generators.

## What Changes
- Clean-room `HlslBackend` materials reproduced under compatibility aliases: felt, leather grain, burlap and leather pattern, built on the shared primitive library, with parameters and physical size as Painter documents them; every material output (one per channel) reachable through `output_mapping`.
- Physical-size handling through the `MaterialPhysicalSize` and `CustomPhysicalSize` scale modes and the unit rule of `docs/architecture/12-mesh-import.md` §3; effective units recorded.
- Calibration black-box against private Painter oracles; one provenance record per family (public sources, author, calibration corpus id, residuals), parity status per asset and output, Tier 2a manifests under `parity/manifests/`.

## Dependencies
- Prerequisites: `phase3.1_proc-backend-seam`.
- Parent: `phase3.3_procedural-families`. Feeds `phase3.6_smart-presets-projections` (P3-SMART) through the parent.

## Acceptance
Tier 2a for every output of each material over the certification matrix (unit sphere, bevelled cube, hat v6 low × {1024, 2048, 4096} × {defaults, recipe sets, two boundary sets} × {recorded seed, one other}): exact, or an owner-approved exception per asset; otherwise a release gap.

## Impact
- Affected specs: procedural
- Affected code: material kernels in `HlslBackend`, physical-size scale handling, Tier 2a manifests
- Breaking change: NO
- User benefit: the leather and fabric materials the locked recipes use, without Adobe's runtime
