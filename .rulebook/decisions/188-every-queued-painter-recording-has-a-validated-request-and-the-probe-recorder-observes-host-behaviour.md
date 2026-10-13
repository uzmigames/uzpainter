# 188. Every queued Painter recording has a validated request, and the probe recorder observes host behaviour

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.15_compositor-colour-fits, phase1.25_pilot-wand, phase1.24_python-api-facade, phase2.1_preview-display-presets, phase3.3_unreal-gltf-presets

## Context

The Painter recording queue still listed recordings with no request, so a Painter window could not simply run them:

- decision 174 item 6, bilinear minification of an sRGB bitmap (colour-fits item 2.5);
- decision 169, the export of an L8 material channel (release gap `l8-material-channel-png`);
- P20-A, the fill channel defaults (decision 107; colour-fits item 2.1);
- P20-B, authored as one 645-step request that decision 180 stopped at the time cap;
- P21-A to P21-G (decisions 109 and 110), R-132-A, B and D (decision 132), R-095 P7 (decision 095), and decision 084's held-out minification.

The phase1 API-probe family accepted only a BaseColor export, and the probe recorder had no vocabulary for mesh maps or folders at create, shelves, the display, the camera, default paths, `resource.search`, close and reopen inside a recording, or timed lifecycle calls. The python-doc (A-PYDOC) documents every call these recordings need.

## Decision

1. **Texture requests** (`recording_requests.later_goldens`, `requests/tier0/semantics/`):
   - `srgb-bitmap-minification`. The 8-bit `srgb8-ramp` and field A, set to sRGB on BaseColor. Each at BilinearHQ and BilinearSharp, scales 2 and 4, rotation 0, Repeat, on the 4x2 grid. BaseColor at PNG 16, PNG 8 and OpenEXR 32f.
   - `export-l8-material`. BaseColor edited to L8, with Specular and Emissive added as L8, on the 2x2 grid. The sources are grey A, the 8-bit grey ramp, a uniform 0.37 and the empty base. All three maps as RGB and as L at PNG 8, PNG 16 and OpenEXR 32f (the linear control).
   - `resample-uv-heldout-128px` and `-32px`. Decision 084 item 5: a fresh recording, never fitted, inside the supported domain of decision 084 §3.
     - Rotations are multiples of 90 degrees, on square sets, with Repeat and RepeatNone, for both filters.
     - The bitmaps are new authored square power-of-two patterns of 128 and 32 px (`request_fixtures.held_out_pattern`). No fit has used them.
     - The scales are new (isotropic, and anisotropic on u and on v), with irregular offsets and a zero-offset case. None repeats a scale or offset of decision 078's plans, `resample-uv-minify` or `resample-uv-impulse`.
     - Their records must not enter a fit. They are the held-out check of decision 084.
   - No image name ends in a number of 1001 or more (decision 166).
2. **P20-B in four parts.** `phase1-srgb-uniform-decode-part1..4` hold the same `set_source`/`get_source` pairs in the same order, 80 colours (165 steps) each. The unrecorded 645-step request is deleted.
   - Decision 190 (colour-fits item 2.6) needs the OCIO twin. `phase1-srgb-uniform-decode-ocio-part1..4` are the same four parts, naming `OCIO` (Painter's substance config).
   - The recorder records the twin only in a Session O.
3. **P20-A** is `phase1-fill-channel-defaults`.
   - On the plane with no template, a fresh fill is assigned the five default channels and read back per channel.
   - The checker and the left-half mask are bound on every channel and as mask sources, with their colour spaces read.
   - Every channel is exported at PNG 16.
   - The phase1 probe test now takes each probe's exported maps. The fake's no-template project holds 12.1.5's default channels.
4. **Probe recorder vocabulary.** All of it is documented API only, and `documented_symbols.json` names the python-doc object of every new symbol. RECORDER.md §9 lists it:
   - `create` takes `mesh_maps` (input ids as `mesh_map_file_paths`) and the `default_save_path` / `export_path` folders, which the host makes in the private work directory.
   - New edits: `insert_paint`, `insert_anchor_point_effect`, `remove_mask`, `set_mask_background`, `reset_source`, `set_symmetry_enabled`, `SourceUniformColor.set_color`, `SourceBitmap.reset_color_space`, the display setters, `Camera.<property>` setters, `Shelves.add`, `Shelf.refresh`, and `project.close` / `open` with the inserted nodes found again.
   - New getters: the camera, the display state, the scene bounding box, `get_default_export_path`, the throttling period, the shelves and `resource.search`.
   - An export probe can run without `exportPath`, and its file locations are recorded relative to the run.
   - The probe recorder also gains:
     - shelf crawls and opens as pending states;
     - the shelf and camera events;
     - a timed lifecycle (marker and a second polling thread);
     - removal of added shelves after the project closes;
     - the OCIO/Legacy session guard of texture goldens.
   - Three event constructor parameters are added to the capability inventory as `release-gap`, like `BusyStatusChanged.busy`.
5. **Host behaviour requests** (`requests/tier0/api-probes/`):
   - `phase1-create-mesh-maps` (P21-A). It covers the seven mesh-map names the documented export configuration lists, as `uzp_plane_<name>`, with all ten usages read back. BentNormals, Height and Opacity have no documented name and are read only.
   - `phase1-create-default-paths` (P21-B).
   - `phase1-texture-throttling` (P21-C), first in a fresh session.
   - `phase1-shelves` (P21-D).
   - `phase1-layer-stack-events` (P21-E). It covers the decision 110 §4 calls the vocabulary reaches. `instantiate` and `set_material_source` need an instance source and a material resource and are left out.
   - `phase1-create-open-timing` (P21-F).
   - `phase1-close-without-saving` (P21-G).
   - `phase1-default-camera-{plane,sphere,bevelled-cube}` (R-132-A).
   - `phase1-camera-coupling` (R-132-B).
   - `phase1-display-ocio` (R-132-D, OCIO session).
   - `phase1-export-preset-search` (R-095 P7). With `export-presets-legacy` and `-ocio` admitted (decision 180), R-095's other probes are recorded.
   - R-132-C is a live Iray capture, not an API probe, and stays with the Iray procedure.
6. **Validation.** Every request validates against `golden-public.json` and loads as a recorder job. Each probe request records `r1` and `r2` end to end against the fake Painter, with a test per new behaviour. The tier0 semantics check passes. RECORDER.md §11.4 is the runbook.

The model panel was not consulted on this decision: each request follows its decision's text. The P22-B scope split went to the panel (decision 189).

## Alternatives Considered

- **Put R-132 in texture jobs through the camera state steps and `render_state`.** Rejected. A texture job reads back only what it set, so the default camera cannot be read. `render_state` belongs to the Iray recorder.
- **Guess Painter's mesh-map suffixes for the three undocumented usages.** Rejected. An unbound file may refuse `create`, and the guess is not documented.
- **Keep P20-B as one request.** Rejected. It did not fit a Painter window (decision 180).

## Consequences

- The next Painter batch runs RECORDER.md §11.4 with no authoring left: a Legacy session, then a Session O for `phase1-display-ocio` and the four OCIO parts of P20-B.
- `tests/parity/recorder/test_texture_recording.py::test_every_recorded_manifest_keeps_its_record_ids` fails on main for `phase1-engine-computations` (admitted by decision 180). This change does not cause it, and it belongs to the batch-D owner.
