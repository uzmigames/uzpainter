# Proposal: phase2.1_preview-viewport-window

## Why
Child of `phase2.3_realtime-preview` (P2-PREVIEW in `docs/dag.md`), implementing the preview half of D6 (`docs/architecture/07-preview-and-render-parity.md` §1, §3.4, §6; decision 018, owner Q2). The owner watches the work through a read-only preview, and agents need a fast visual check; neither may slow or pause evaluation, and the realtime viewport is never the parity target (Iray is, through `painter_iray` in Phase 3). Requirements: VIS-01, NFR-01, ARC-06 (`docs/prd.md`).

## What Changes
- `painter_viewport`: a forward rasterised pass on the vendored render core using the project's material parameters and the display transform of `07-…` §3.4, pinned by decision 038 to OCIO through OpenColorIO with Painter's substance config (pinned by hash) and the view `Default - sRGB` (decision 042); Legacy `Linear`, Legacy `ACES`, ACE mode and every other OCIO view are pinned out by decision 038 and fail explicitly before rendering with an unsupported-configuration error, evaluated with realtime approximations from public literature: split-sum image-based lighting (Karis 2013), SH irradiance (Ramamoorthi and Hanrahan 2001) and the GGX/Smith/Schlick/Burley lobes; normals in the MikkTSpace frame.
- Preview window: `UzPainter.exe --preview <file.uzp>` or attached to a worker; read-only, orbit camera only (vendored `platform_window` and `input`), renders `painter_viewport` at a low rate on the preview thread from the double-buffered last evaluation; it can never block the engine thread; it shows the latest `painter_iray` capture when one exists and states that the mode is unavailable otherwise.
- Fast check: UzPainter-vs-UzPainter viewport regression goldens (exact for a fixed build, adapter and driver) on UzmiGames-authored fixtures (sphere, plane, bevelled cube); never Tier 3 and never acceptance evidence.

## Dependencies
- Parent: `phase2.3_realtime-preview`.
- Prerequisite: `phase1.25_pilot-wand` (DAG input of P2-PREVIEW; through it the render-core layer, compositor and export exist).
- Sibling: `phase2.2_preview-capture` builds on this pass.

## Acceptance
- Viewport regression goldens reproduce exactly in a local run on the owner's machine (decision 028; the local run report is the evidence) for a fixed build, adapter and driver.
- With the preview window open, minimised, resized or its thread stalled by a test hook, evaluation and export complete without waiting on the preview thread.
- An unsupported display configuration (Legacy `Linear` or `ACES`, ACE mode, another OCIO view) fails with an explicit error naming decision 038 before rendering.

## Impact
- Affected specs: `preview` (viewport pass, preview window)
- Affected code: render code on the vendored core (forward pass, IBL precomputation, display transform), preview thread and window
- Breaking change: NO
- User benefit: a live read-only view of the work that never slows evaluation
