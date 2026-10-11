# Proposal: phase3.2_proc-filter-families

## Why
MAT-03 and MAT-04 require the procedurals used by recorded and locked recipes to evaluate identically through UzPainter's own implementations, and LAY-04 lists sharpen among the mask operations (`docs/prd.md`, decision 002). The filter family (Sharpen for hat v8, grayscale conversion, Levels) is listed in `docs/architecture/05-procedural-content.md` §3 (D4). This child of P3-PROC (`phase3.3_procedural-families`) is split out beyond the DAG rule's examples because filters take layer content rather than mesh maps or seeds and are certified independently.

## What Changes
- Clean-room `HlslBackend` filters reproduced under compatibility aliases: Sharpen and grayscale conversion, written from standard image-processing operators and calibrated black-box against private Painter oracles; inputs are the layer content at the filter's position in the effect list (`docs/architecture/04-layer-stack-and-compositing.md` §2 step 4).
- The Levels filter mapped onto the native levels effect whose semantics Tier 0 settled (`04-layer-stack-and-compositing.md` §9), certified as a filter asset.
- The starter-asset Blur filter (the `effect-order` Tier 0 golden's filter B: resource search `s:starterassets u:filter n:Blur=`, default parameters) reproduced from the shared blur operators of `phase3.1_proc-backend-seam` and calibrated against that golden: `effect-order` s0–s5 and s7, which hold it, settle the content-effect order of fill and levels effects that `phase1.11_compositor-mask-effects` implements from the documented list order (decision 069).
- `ResolutionOverride` restriction for sources used by a Filter effect enforced (`05-procedural-content.md` §7).
- One provenance record per family (public sources, author, calibration corpus id, residuals), parity status per asset and Tier 2a manifests under `parity/manifests/`.

## Dependencies
- Prerequisites: `phase3.1_proc-backend-seam`.
- Parent: `phase3.3_procedural-families`.

## Acceptance
Tier 2a for Sharpen, grayscale conversion and the Levels filter over the certification matrix (unit sphere, bevelled cube, hat v6 low × {1024, 2048, 4096} × {defaults, recipe sets, two boundary sets}; filters take content instead of seeds): exact, or an owner-approved exception per asset; otherwise a release gap.

## Impact
- Affected specs: procedural
- Affected code: filter kernels in `HlslBackend`, filter-effect evaluation, Tier 2a manifests
- Breaking change: NO
- User benefit: hat v8's Sharpen and the recipes' grayscale/levels filters without Adobe's runtime
