# Proposal: phase3.2_proc-grunge-families

## Why
MAT-03 requires exact evaluation of the procedural sources used by recorded recipes (a generic noise library SHOULD exist) and MAT-04 requires the starter assets used by locked or delivered recipes to evaluate identically through UzPainter's own certified implementations (`docs/prd.md`, decision 002). The body and hat recipes reference grunge and noise procedurals. This child of P3-PROC (`phase3.3_procedural-families`) implements the grunges-and-noises family of `docs/architecture/05-procedural-content.md` §3 (D4).

## What Changes
- Asset inventory: the grunge, dirt, spots, scratches, rust, humidity and cracks procedurals referenced by the body and hat recipes that `docs/architecture/05-procedural-content.md` §1 names (UzmiGames recipe files) plus `fabric_linen`, each with its compatibility alias.
- Clean-room `HlslBackend` implementations built on the shared primitive library (Perlin, simplex, Worley, fBm), with tiling, seed and parameters as Painter documents them, calibrated black-box against private Painter oracles.
- One provenance record per family (public sources, author, calibration corpus id, residuals) and parity status per asset.
- Tier 2a manifests under `parity/manifests/` for each asset.

## Dependencies
- Prerequisites: `phase3.1_proc-backend-seam`.
- Parent: `phase3.3_procedural-families`.

## Acceptance
Tier 2a for each inventoried asset over the certification matrix (unit sphere, bevelled cube, hat v6 low × {1024, 2048, 4096} × {defaults, recipe sets, two boundary sets} × {recorded seed, one other}): exact, or an owner-approved exception per asset; an asset that is neither stays a release gap in the capability manifest.

## Impact
- Affected specs: procedural
- Affected code: grunge and noise kernels in `HlslBackend`, provenance records, Tier 2a manifests
- Breaking change: NO
- User benefit: the grunges the body and hat recipes use, evaluated without Adobe's runtime
