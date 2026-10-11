# Proposal: phase2.1_preview-display-presets

## Why
Child of `phase2.3_realtime-preview` (P2-PREVIEW in `docs/dag.md`), implementing the display presets, environments and cameras of D6 (`docs/architecture/07-preview-and-render-parity.md` §2.1 camera model, §3.4, §7; `docs/architecture/03-project-model.md` §1, §3; decision 018). Captures and previews must be reproducible from serialisable display state that matches the pipeline's comparison standard, environments must be identified by content, and cameras must convert to the Blender convention the pipeline uses. Requirements: VIS-04, VIS-05, RES-03, CLR-06 (`docs/prd.md`).

## What Changes
- Serialisable display preset `{environment {sha256, exposure, rotation, dome}, background, ground, display configuration (tone mapping or OCIO view), cameras, samples, seed}`, separate from presentation snapshots; the pipeline's common comparison standard and its `ref_match` preset implemented from `A3D\Pipeline\render\Render-Comparison-Standard.json` (UzmiGames file).
- Environments stored in the project as bytes plus SHA-256; a preset naming a missing environment fails explicitly, never with a substitute.
- Shipped CC0 environments (Poly Haven) under UzPainter names in `assets/`, each with `<name>.provenance.json` (`docs/licensing-and-clean-room.md` §6); Adobe environments are never shipped or committed.
- Camera model of Painter's documented API (position, rotation in Euler degrees, projection type, field of view 3–179°, focal length 1–500 mm, orthographic height, focus distance, aperture) in its Y-up scene space, with import/export in the Blender convention per `Render-Comparison-Standard.json → coordinate_contract`.
- Display state API: native `uzpainter.render.display` (`set_exposure/rotation/opacity/blur/shadows/background`), `uzpainter.render.shader` (`parameters/set_parameters`) and the documented `substance_painter.display` symbols for environment, colour LUT, tone mapping (raising `RuntimeError` on a colour-managed project, as documented) and cameras; worker command handlers for the MCP `display_*`, `shader_*` and `camera_*` tools.

## Dependencies
- Parent: `phase2.3_realtime-preview`.
- Prerequisite: `phase1.25_pilot-wand` (DAG input of P2-PREVIEW).
- Consumer: `phase2.2_preview-capture`.

## Acceptance
- Preset round-trip is lossless; `ref_match` equals the pipeline standard's values.
- A missing environment hash fails explicitly.
- The camera conversion fixture round-trips between Painter's convention and Blender's and matches the pipeline standard's coordinate contract.
- Every shipped environment has a valid provenance record.

## Impact
- Affected specs: `preview` (display presets, environments, cameras)
- Affected code: display state model and API, preset serialisation, camera conversion, shipped environment assets
- Breaking change: NO
- User benefit: reproducible preview and capture conditions matching the pipeline's comparison standard
