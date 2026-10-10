# Proposal: phase2.1_preview-viewport-window

## Why
Child of `phase2.3_realtime-preview` (P2-PREVIEW in `docs/dag.md`), implementing the preview half of D6 (`docs/architecture/07-preview-and-render-parity.md` §1, §3.4, §6; decision 018, owner Q2). The owner watches the work through a read-only preview, and agents need a fast visual check; neither may slow or pause evaluation, and the realtime viewport is never the parity target (Iray is, through `painter_iray` in Phase 3). Requirements: VIS-01, NFR-01, ARC-06 (`docs/prd.md`).

## What Changes
- `painter_viewport`: a forward rasterised pass on the vendored render core using the project's material parameters and the display transform of `07-…` §3.4 (Legacy `Linear` per IEC 61966-2-1 with values above 1 clamped, Legacy `ACES` through the Academy's public transforms, OCIO through OpenColorIO with the project's pinned config and view; any unsupported configuration, including ACE mode until qualified, fails explicitly before rendering), evaluated with realtime approximations from public literature: split-sum image-based lighting (Karis 2013), SH irradiance (Ramamoorthi and Hanrahan 2001) and the GGX/Smith/Schlick/Burley lobes; normals in the MikkTSpace frame.
- Preview window: `UzPainter.exe --preview <file.uzp>` or attached to a worker; read-only, orbit camera only (vendored `platform_window` and `input`), renders `painter_viewport` at a low rate on the preview thread from the double-buffered last evaluation; it can never block the engine thread; it shows the latest `painter_iray` capture when one exists and states that the mode is unavailable otherwise.
- Fast check: UzPainter-vs-UzPainter viewport regression goldens (exact for a fixed build, adapter and driver) on UzmiGames-authored fixtures (sphere, plane, bevelled cube); never Tier 3 and never acceptance evidence.

## Dependencies
- Parent: `phase2.3_realtime-preview`.
- Prerequisite: `phase1.25_pilot-wand` (DAG input of P2-PREVIEW; through it the render-core layer, compositor and export exist).
- Sibling: `phase2.2_preview-capture` builds on this pass.

## Acceptance
- Viewport regression goldens reproduce exactly on the self-hosted GPU runner for a fixed build, adapter and driver.
- With the preview window open, minimised, resized or its thread stalled by a test hook, evaluation and export complete without waiting on the preview thread.
- An unsupported display configuration fails with an explicit error before rendering.

## Impact
- Affected specs: `preview` (viewport pass, preview window)
- Affected code: render code on the vendored core (forward pass, IBL precomputation, display transform), preview thread and window
- Breaking change: NO
- User benefit: a live read-only view of the work that never slows evaluation
