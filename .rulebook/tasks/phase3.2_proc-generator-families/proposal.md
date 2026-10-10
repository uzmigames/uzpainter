# Proposal: phase3.2_proc-generator-families

## Why
MAT-02 requires mesh-map generators (edge wear, cavity dirt, ground dirt/dust) with Painter's parameters, and those used by delivered or locked recipes must evaluate identically; MAT-04 requires the starter assets used by those recipes to be reproduced by UzPainter's own certified implementations (`docs/prd.md`, decision 002). This child of P3-PROC (`phase3.3_procedural-families`) implements the mesh-map generator family of `docs/architecture/05-procedural-content.md` §3 (D4), building on the P0-FEAS-PROC calibration of two generators.

## What Changes
- Clean-room `HlslBackend` implementations of the mesh-map generators reproduced under compatibility aliases: Mask Builder (Legacy), Mask Editor, Metal Edge Wear, Dirt, Curvature, Position, World Space Normals and Ambient Occlusion generators; inputs AO, curvature, position, WSN and thickness mesh maps bound by usage, plus parameters.
- Written from public literature (edge/cavity detection from curvature and AO maps, morphological and blur operators, procedural noise from the shared primitive library) and the parameter semantics Adobe documents publicly (names, ranges and labels discovered through the `Property` API); calibrated black-box against private Painter oracles.
- One provenance record per family (public sources, author, calibration corpus id, residuals) and parity status per asset (`exact` or `calibrated{…}`).
- Tier 2a manifests under `parity/manifests/` for each generator.

## Dependencies
- Prerequisites: `phase3.1_proc-backend-seam`, `phase0.6_procedural-feasibility` (calibration residuals and go/no-go for the two feasibility generators).
- Parent: `phase3.3_procedural-families`.

## Acceptance
Tier 2a for each generator over the certification matrix (unit sphere, bevelled cube, hat v6 low with its mesh maps × {1024, 2048, 4096} × {defaults, recipe sets, two boundary sets} × {recorded seed, one other}): exact, or an owner-approved exception per asset; an asset that is neither stays a release gap in the capability manifest.

## Impact
- Affected specs: procedural
- Affected code: mesh-map generator kernels in `HlslBackend`, generator provenance records, Tier 2a manifests
- Breaking change: NO
- User benefit: the edge-wear and dirt generators the Assets3D recipes depend on, without Adobe's runtime
