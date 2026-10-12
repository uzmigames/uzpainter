# `phase2.1_preview-display-presets`: local run on the owner's machine

This task is a child of `phase2.3_realtime-preview` (P2-PREVIEW; `docs/architecture/07-preview-and-render-parity.md` §3.4, §7; `03-project-model.md` §1, §3; VIS-04, VIS-05, RES-03, CLR-06). This report holds its results for `phase2.3_realtime-preview`.

Run on 2026-10-12, branch `wt/p2-preview-presets`, on main `646933c`. Decisions 038, 042 and 132. Implementation: `src/python/display.{h,cpp}` and `bind_display.cpp` (`src/python/PYAPI.md`, Display), the facade's `display` (`python/FACADE.md` §10), the worker's `display_*`, `shader_*` and `camera_*` tools (`src/supervisor/SUPERVISOR.md`), and `assets/environments/`. Everything is CPU only; no GPU test was run.

## Result

`tests/python/test_display_presets.py`: 7 of 7 pass.

| Item | What passed |
|---|---|
| 3.1 | A `ref_match` preset with a project environment, rotation 180, one camera and seed 7 is serialised, loaded into a new project and serialised again, and is byte-identical; after save and reopen it is identical again. A new project's preset is `common` with no environment. `presets()` equals the values read from `Render-Comparison-Standard.json` (SHA-256 `2ec4281f…` checked first) for both presets: environment hashes, sliders, dome, colour space, shadows, clear colour or expected background, ground, display transform, post effects and 256 samples. |
| 3.2 | A preset naming the `ref_match` HDRI, which the project does not store, raises `ResourceNotFoundError` naming the hash and "no substitute". A texture's hash given as the environment raises the same error. A PNG imported as an environment raises `ValueError`. The revision, the preset and the environment (None) are unchanged. |
| 3.3 | Five axis-aligned Painter cameras, one of them decision 046's fixture camera, convert to the contract's Blender location and Euler angles exactly; yaw θ becomes Blender (90, 0, θ). They also convert back exactly, to the canonical angles of the same matrix. On a general camera, the Blender matrix equals `B @ Rx @ Ry @ Rz` within 1e-12 per entry, and the round trip returns the angles within 1e-9 degrees with the position and lens unchanged. An orthographic Blender camera returns unchanged. Painter's `Camera` properties raise `NotYetSupported` while no camera is set and for the coupled `field_of_view` and `focal_length` setters. They refuse an aperture other than 0 and an out-of-range record. |
| 3.4 | Thirteen values outside the pipeline raise `UnsupportedInUzPainter` naming the setting, the accepted values and decision 038, with the revision, preset and shader unchanged: exposure, opacity, blur, rotation, shadows, background, a colour LUT (set and import), two shader parameters, both tone-mapping calls on a Legacy project and a preset's exposure. The pipeline's own values are accepted as no-ops. On a bundle whose manifest declares OCIO, `get_tone_mapping` and `set_tone_mapping` raise `RuntimeError`. The facade's `substance_painter.display` sets and reads back a Painter-shaped environment id. |
| 3.5 | `assets/environments/studio-small-09.exr` (Poly Haven "Studio Small 09", CC0, 1024 × 512 OpenEXR, SHA-256 `44dcbed0…`, the API's MD5 matched) has a record valid under `src/python/environment-provenance.schema.json`, with matching hash, size and dimensions. |

Other affected tests:
- `tests/python/test_capability_conformance.py`: 5 of 5. The display symbols are `pending-evidence`, with their accepted values in the notes.
- `tests/python/test_pyapi_facade.py`: all pass. `alg.shaders.*` failed on the first run because it had been mapped onto the native shader calls. It now raises its own `NotYetSupported` (decision 132 §7), and the re-run passes.
- `test_pyapi_native.py::test_later_phase_calls_raise_not_yet_supported_before_mutation`: passes.
- `tests/python/test_pyapi_recipe.py`: 4 of 4 pass. A new project's display state stays outside the recipe digest (decision 122).
- `tests/supervisor/test_supervisor_mcp.py`: `test_tools_are_forwarded_and_stdout_carries_protocol_frames_only` and `test_display_shader_and_camera_tools_hold_the_fixed_pipeline` pass.

Quality gate: ruff check, ruff format and mypy strict pass on the touched Python, and the facade's mypy run passes. `zig build pyapi-tests` and `zig build painter` compile with `-Werror`.

## Open

- Item 1.1 (prerequisite `phase1.25_pilot-wand`) stays open while G1 is open, so the task is not archived.
- Recordings R-132-A to R-132-D (decision 132 §9, owner's Painter session):
  - Painter's default camera;
  - the fov ↔ focal-length coupling and clamps;
  - the `ref_match` side-view rotation sign;
  - a Tier 0 replay of the display symbols on an OCIO project, which moves the manifest entries from `pending-evidence`.
