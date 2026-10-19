# 132. Display presets follow the standard per preset; a project has no camera until one is set, and the Painter lens coupling stays refused

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.1_preview-display-presets, phase2.3_realtime-preview, phase2.2_preview-capture

## Context

Task `phase2.1_preview-display-presets` implements the display state of the fixed render pipeline (decisions 038 and 042): serialisable presets, environments by content, cameras with Blender conversion, and the documented `substance_painter.display` symbols, the native `uzpainter.display`, `uzpainter.render.display` and `uzpainter.render.shader`, and the worker's `display_*`, `shader_*` and `camera_*` tools. Facts it rests on:
- `Render-Comparison-Standard.json` (`U-A3D-RENDERSTD-2`, SHA-256 `2ec4281f…`) has two Painter presets. The v2 block lights with "Studio White Soft", an Adobe starter asset that is never shipped (its file SHA-256 `c2bb3294…`): exposure 0, rotation 0, opacity 0, blur 0, infinite sphere, no ground, shadows off, clear colour on with an expected background of sRGB8 89,89,89, OCIO `Default - sRGB`, no LUT, no post effects, Iray 256 samples. `presets.ref_match` v3 lights with `TOS-RefMatch-Skeletal-Mage.exr` (`77eeed8d…`), shadows on and clear colour 141,142,148. Its envRotation is 0 for the front view and follows the camera yaw for back and side views (180, and ±90 "sign to be verified live").
- Painter's public `display` documentation describes the camera's `field_of_view` (clamped 3–179) and `focal_length` (clamped 1–500 mm). Each changes the other, so they are coupled. `focus_distance` is clamped to 10 × the scene radius and `aperture` (the lens radius) to the scene radius. Neither Painter's default camera of a new project nor the sensor size that couples fov and focal length is recorded.
- The default `open-pbr` instance was read back under OCIO (`parity/reports/phase0/iray-references.md` §5, decision 042). The panel shows labels only; no documented parameter identifiers exist.
- Every project UzPainter creates today is Legacy: OCIO creation is gated by phase1.14. Painter documents `RuntimeError` from `get/set_tone_mapping` on a colour-managed project.

Model panel under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5, 2026-10-12):
- A new project starts on the `common` preset with no environment; the seed is UzPainter's own: PARTLY ×3. A missing or non-standard environment must report non-parity, and the seed needs a bound.
- Rotation, shadows and clear colour are checked against the active preset, and presets switch only whole: PARTLY ×3. The ±90 sign is unverified, so no value may be normalised.
- Any stored environment is accepted and reported as non-parity unless it is the preset's: PARTLY ×3. Magic bytes are not enough; the image must be checked, and the parity flag needs a defined place.
- No camera until one is set, with fov and focal length only as a whole record: PARTLY ×3. A stored pair is not checked for consistency, and the scene radius for the clamps is undefined.
- Blender conversion `B @ Rx @ Ry @ Rz` with canonical Euler angles: AGREE, PARTLY, DISAGREE. The objections: the decomposition is not unique, so a round trip is exact only on canonical angles; sin and cos need an exact table at multiples of 90; one model asked for a check of the left multiplication on yaw cameras.
- Shader identifiers are UzPainter's own names for the read-back panel settings: AGREE ×2, PARTLY ×1. They are native identifiers, not Painter keys, and need an explicit label map.
- The tone-mapping `RuntimeError` is tested on a hand-written OCIO bundle: AGREE ×2, PARTLY ×1. It needs a companion Legacy test and the message text checked.

## Decision

1. **Presets.** A preset is `uzpainter/display-preset/1` JSON. It holds `name` (`common` | `ref_match`), `standard` (source, file SHA-256, block, version), `environment {sha256, exposure, rotation, opacity, blur, dome, color_space, shadows}`, `background {clear_color, srgb8}`, `ground`, `display {mode, config, config_sha256, view, color_lut, post_effects}`, `cameras` (none or one), `samples` and `seed`.
   - Every pinned field must equal the standard's value for that preset.
   - Three fields vary: the environment (a SHA-256 the project stores, or null), the rotation (0 under `common`; 0, 90, −90, 180 or 270 under `ref_match`, stored as given and never normalised) and the camera. The seed is an integer 0…2³²−1 that drives UzPainter's own sampler; Iray's seed is uncontrolled (decision 039).
   - `apply_preset` validates everything, then checks that the environment is stored, and commits once or not at all.
2. **New projects** start on the `common` preset with no environment, because the standard's environment cannot be shipped, and with the default `open-pbr` shader. `render.display.state()` reports `parity`: true only when the environment is the active preset's standard environment. A missing or other environment is a non-parity preview.
3. **Setters per preset.** `set_rotation`, `set_shadows` and `set_background` accept only the active preset's values. Exposure, opacity and blur accept only 0. Presets switch only through `apply_preset`. A refusal raises `UnsupportedInUzPainter`, naming the setting, the accepted values and decision 038, and changes nothing.
4. **Environments** are imported with `Usage.ENVIRONMENT` as unmodified bytes under their SHA-256. The file must be a single-part OpenEXR whose data window is twice as wide as high (an equirectangular map, checked by parsing its header); anything else raises `ValueError`. A preset or setter naming a hash the project does not store as an environment raises `ResourceNotFoundError` and never substitutes. Importing a `COLOR_LUT` raises `UnsupportedInUzPainter`, because the colour LUT is pinned to none.
5. **Cameras.** A project has no camera until a whole record is set: `uzpainter.display.set_camera`, a preset or `camera_set`.
   - `Camera.get_default_camera()` returns the handle. Reading or setting a property of an unset camera raises `NotYetSupported` naming recording R-132-A.
   - On a set camera, single properties can be set, except `field_of_view` and `focal_length`. Those two raise `NotYetSupported` naming recording R-132-B, because the coupling Painter applies is unrecorded. A whole record stores both as given.
   - A record outside the documented ranges raises `ValueError`; it is not clamped, because the scene-radius clamps are undefined without recording R-132-B.
   - `aperture` accepts only 0: the fixed pipeline renders without depth of field.
6. **Blender convention** (the standard's `coordinate_contract`):
   - Position maps `(x, y, z) → (x, −z, y)`.
   - The rotation matrix `B @ Rx @ Ry @ Rz`, where `B` is that basis change, is decomposed into Blender's XYZ Euler angles on the canonical branch (Y in [−90, 90], the others in (−180, 180]). Sines and cosines of multiples of 90° are exact.
   - Lens values pass unchanged (`angle_degrees`, `lens_mm`, `ortho_scale`, `focus_distance`, `aperture_radius`).
   - Axis-aligned cameras round-trip exactly, and canonical angles return unchanged. A non-canonical input returns as the canonical angles of the same matrix: the back view's yaw 180 returns as (180, 0, 180).
   - On general angles, the round trip and the contract's matrix agree to float64 rounding (≤ 1e-9° and 1e-12 per matrix entry). This is a coordinate change, not a parity residual against Painter.
   - The left multiplication is checked on yaw cameras: Painter yaw θ becomes Blender (90, 0, θ).
7. **Shader parameters** are UzPainter's native identifiers for the read-back panel settings. The map from identifier to panel label is in `display.cpp` `ShaderDefaults` and `src/python/PYAPI.md`. `set_parameters` accepts a known identifier only at its default value and raises `UnsupportedInUzPainter` otherwise. Painter's own keys (`alg.shaders`) stay behind `js.evaluate`'s `NotYetSupported`.
8. **Tone mapping.** `get/set_tone_mapping` raise `RuntimeError` on a colour-managed project (any mode other than Legacy) and `UnsupportedInUzPainter` on a Legacy one. The `RuntimeError` branch is tested on a bundle whose canonical manifest declares OCIO, which is the only way to open such a project before phase1.14. The Legacy branch and the message texts are tested too.
9. **Recordings.** These settle the gaps. The owner runs them when Painter is free.
   - R-132-A: Painter's default camera after `project.create` on the fixture meshes, all eight properties.
   - R-132-B: the fov ↔ focal-length coupling and the clamps. Set each property across and outside its range and read both back.
   - R-132-C: the sign of the `ref_match` side-view rotation, in a live capture.
   - R-132-D: a Tier 0 replay of the display symbols on an OCIO project: environment set and get with a project EXR (the resource URL's version), `set_color_lut_resource(None)`, tone mapping raising `RuntimeError`, the camera properties' read-back precision, and whether a display change makes `needs_saving()` true. Until then the manifest entries are `pending-evidence`.

## Alternatives Considered

- Invent a default camera, such as decision 046's fixture camera (rejected: not Painter's; reading it would claim a recorded value).
- Derive focal length from fov with a 35 mm sensor (rejected: the sensor size and axis are unrecorded).
- Clamp out-of-range camera values as Painter documents (rejected: the focus and aperture clamps need the scene radius, which is unrecorded; a whole record from Blender would change silently).
- Accept every preset's varied values at any time (rejected: a mix such as the v2 background with `ref_match` shadows is no pipeline state).
- Normalise −90 to 270 (rejected: the sign is unverified and the getter must return what was set).

## Consequences

The display state covers exactly the standard's two presets. Phase2.2 capture and the viewport read `render.display.state()` and refuse a Legacy project or a non-parity state for parity evidence. A change of the standard re-opens this decision, as decision 038 says. Recordings R-132-A to R-132-D are owner actions; until they are made, the camera's default, the coupled lens setters and the Tier 0 evidence stay open.

## Amendment (2026-10-19, decision 196)

Item 7 is amended for `double_sided` only. Decision 196's amendment adopts its option (b): `set_parameters` and `shader_set` accept `double_sided` true or false and merge into the stored parameters. A value of any other type is a `ValueError`. The other identifiers stay default-only. Item 2's `parity` also needs every stored shader parameter at its default.
