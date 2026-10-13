# 194. Tunic v10 is recorded as a migration golden from its Painter project, and its rebuild waits on nine masks only that project holds

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase2.10_pilot-tunic-recovery, phase2.9_pilot-belt, phase1.25_pilot-wand

## Context

phase2.10 is the Tunic v10 pilot (Skeletal Mage `18-Tunica` v10), the milestone that counts. It has 2 groups (the lining group has the mask `M_lining` and `replace_height`), 22 fills, and per-layer bindings: C07 binds the v10 `M_piping` and F03 the v9 one, through the recorded override F03 → `M_piping_lining_v9`. The Belt lost its inputs when Assets3D `_tmp` was cleaned (decision 192), so the first step was to secure the Tunic's.

Measured facts (2026-10-12):

- **No pipeline round exists.** The tunic was painted interactively from v4 to v10. No create or export script and no arguments file exist. The recipe is committed in `18-Tunica/report.json` (`painting_v10.painter_stack_recipe` and `source_recovery.layer_specific_masks`).
- **Everything else is git-ignored in Assets3D**, so it was at risk like `_tmp`:
  - `18-Tunica-v10.spp` (408,723,056 B, sha256 `c43db46a…`, the hash the piece manifest `manifests/v10.json` verifies; the report's older `44c95836…` predates a later save);
  - `18-Tunica-v10.blend` (`f6243a57…`);
  - the five delivered maps in `Textures/` (hashes equal to the report's);
  - `Export/18-Tunica-v10.fbx` and `.glb`.

  All ten files and `report.json` are now in the private store by SHA-256.
- **The `.blend` packs the masks v10 changed.** Read with Blender 5.2.2 (`image.packed_file.data`, the route the report records) from a copy of the stored blob:
  - the 7 `Source_v10_M_*` masks, whose SHA-256 equal the report's `mask_resources`;
  - the 7 `Source_v9_M_*` masks they replaced, including the v9 `M_piping`;
  - `Source_v6_HighNormal`;
  - older sources.

  All of these are in the private store too.
- **A Painter resource's `version` is the SHA-1 of the imported file's bytes.** All 14 packed masks and `Source_v6_HighNormal` match the resource URLs the report recorded, byte for byte. That includes F03's `v9_M_piping_ccf485` and the project's Normal mesh map `Tunic_v6_HighNormal` (`a5de3314…`). So C07 binds the v10 piping (sha256 `822f926d…`), and F03 binds the v9 piping (sha256 `9b2b3063…`).
- **Nine masks the v10 stack binds exist nowhere as files:** `M_pores`, `M_fiber`, `M_dyeinv`, `M_stains`, `M_fray`, `M_hem`, `M_cav`, `M_ridgewear` and `M_lining`.
  - The v9 round wrote them to `_tmp/claude/` (the packed v9 masks' file paths), and that folder is gone.
  - They are not packed in the `.blend`, not on drives C, D, E, F or G, and not in any recycle bin.
  - `garment_material_masks.py` regenerates them only to within 1/255 of the composite, not byte for byte.
  - Their only copy is inside the `.spp`, as Painter resources. Painter's documented API cannot export a resource, and a `.spp` reader is forbidden.
- **The mesh file is unknown.** The Painter project's mesh file is not recorded and not on disk. `Export/18-Tunica-v10.fbx` is the same Blender object: 5392 vertices, 11000 triangles, one UV map.

## Model panel (one round: cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5)

| Claim | GPT | Kimi | Grok |
|---|---|---|---|
| C1 The golden is a migration golden: open a hash-checked private copy of the pinned `.spp`, read its state back privately, export r1, r1-repeat, then r2 after save, close and reopen; a new input kind `painter_project` and interface | PARTLY (verify each field through the documented API; mark the rest unknown; the original stays untouched) | AGREE (the readback must carry F03's and the group mask's resource URLs) | AGREE |
| C2 Export with Painter's shipped Blender preset, 16-bit PNG, 4096 px, infinite padding, no dithering; the delivered maps are a cross-check only | PARTLY (padding and dithering are a proposed configuration, not recovered facts) | PARTLY (pin parameters explicitly, not only a preset name) | PARTLY (confirm dithering) |
| C3 Author the golden's request now, with the same command family | PARTLY (extend the schema and recorder first; keep it independent of the rebuild fixture) | AGREE (gated on the schema) | PARTLY (same gate) |
| C4 The rebuild fixture refuses, listing the nine masks; the eight recovered masks and the Normal map are pinned; nothing is regenerated or extracted | PARTLY (list blockers and assumptions apart) | PARTLY (enumerate every binding with its source; 21 bindings over 17 files) | AGREE |
| C5 The mesh is the delivered FBX, labelled an assumption, checked against the readback's `last_imported_mesh_path` and by the maps | PARTLY (count and UV equality do not prove identity) | AGREE | AGREE |
| C6 Items stay open; no stand-in check; no archive | AGREE (the blockers are parallel branches) | AGREE | AGREE |

The conditions are adopted below, with one exception. C2's "pin the maps, not the preset name" is not adopted for the golden. The delivery was written by the shipped preset, and UzPainter's own `blender-principled-bsdf` layout is still `unconfirmed` (R-095). Inlining that layout would hide any error in it behind a golden that no longer matches the delivery. The shipped preset is fixed by the envelope's Painter build. The golden's exported files record its layout (file names and maps), and the export parameters are pinned explicitly.

## Decision

1. **Migration goldens** (`tools/parity/recorder/migration.py`).
   - **Schema.** The public schema gains:
     - the input kind `painter_project`: a UzmiGames project saved by Painter, named by SHA-256 only and never read by UzPainter;
     - the interface `painter_project_migration`, whose steps are documented calls:
       1. `substance_painter.project.open` (`project`);
       2. `substance_painter.export.export_project_textures` (`config`, an authored `recipe_json` repository file without `exportPath`).
   - **Inputs.** The project resolves in Assets3D, or else from the private store by its hash (decision 144). Painter opens a hash-checked private copy, never the original.
   - **Recordings.**
     - r1 (`same_session`): open, read back, export;
     - r1-repeat (`same_session`): export again;
     - r2 (`after_save_reopen`): save the copy under a new name, close, reopen, read back, export.
   - **Readback** (private). `migration_readback` (`painter_side.py`) records:
     - the mesh path (`project.last_imported_mesh_path`, a documented symbol added to the list);
     - per texture set: resolution, mesh-map resources with versions, channel formats;
     - every node: sources with resource versions, per-channel blending and opacity, visibility, uid and mask, plus its sub-layers and effects.

     The double-sided state has no Python API, so it is not read back.
   - **Command.** `python -m tools.parity.recorder record-migration <request> --assets-root <Assets3D> [--launch]`.
2. **The Tunic v10 request** (`--pilot tunic`, `tools/parity/recorder/tunic.py`).
   - It is `parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase2/tier1/tunic-v10.json`. The project input is pinned at `c43db46a…`. A project that differs from the piece manifest's verified pin is refused.
   - The export configuration is `parity/fixtures/tier1/tunic-v10/export-config.json`:
     - the shipped `Blender (Principled BSDF)` preset;
     - `DefaultMaterial`;
     - PNG 16-bit, `sizeLog2` 12, `infinite` padding, no dithering, no shader parameters.

     The padding and dithering are a proposed migration configuration.
   - The session is OCIO with Painter's substance configuration. The recording records the colour management after open.
   - `--store` kept the project.
3. **The rebuild fixture** (`--pilot tunic-rebuild`).
   - It pins:
     - the report;
     - the stack working copy, with the override applied to F03 only (its SHA-256);
     - every binding (2 groups and 20 masked fills: 21 bindings over 17 files) by SHA-256 and Painter resource version;
     - the Normal mesh map;
     - the mesh (the FBX, labelled an assumption);
     - the double-sided value from the report;
     - the export configuration.
   - The 8 recovered masks and the Normal map resolve from the private store. Each is checked against the report's SHA-256 and resource versions.
   - The nine lost masks are expected back at their original paths `_tmp/claude/<name>.png`. A restored mask's SHA-1 is recorded, to be checked against the golden's readback.
   - Today the command refuses and lists the nine (`MissingInputs`).
4. **Nothing is regenerated, substituted or extracted** (decision 192, C1). The owner can:
   - restore the nine masks' original bytes;
   - accept masks regenerated by `garment_material_masks.py`, which makes a new golden, not the approved v10;
   - choose another route.
5. **Fix the pilot exposed.** `MissingInputs` (decision 192) called `super().__init__`. The recorder's provenance rule refuses that dunder access, so `test_recorder_sources_are_documented_api_only` failed on main. The message is now set as the exception's `args`.

## Blockers, tracked apart (no item is checked on stand-in evidence)

- **Recording (owner's Painter session):** `record-migration` of the Tunic request, then `python -m tools.parity.store record`. It needs nothing else and can run now. It blocks 2.2, 3.1 and 4.1.
- **Nine lost masks (owner):** restore them to `_tmp/claude/`, then run `script_run manifest --pilot tunic-rebuild --store`. This blocks 2.1 (the fixture), 2.3–2.5 and 3.1–3.5.
- **Mesh identity:** check the readback's `last_imported_mesh_path` against the FBX. The maps decide.
- **`infinite` padding (phase1.25 item 2.7):** every pilot export is refused before writing until it lands.
- **1.1:** phase2.9, phase2.2 and phase2.8 are not accepted.

## Alternatives Considered

- **Rebuild the tunic in Painter from the recipe** (the Wand/Belt pattern). Rejected. The nine masks are missing, and the approved state is the project itself.
- **Use the delivered maps as the golden.** Rejected. The recorder did not record them, and the Painter build and export parameters are unknown. They stay a cross-check.
- **Regenerate the nine masks.** Rejected (decision 192, C1): not byte-exact, so not the approved v10.

## Consequences

- The owner can record the Tunic golden in the next Painter session, independently of the lost masks.
- The migration readback will give each layer's resource version. A restored mask can then be checked byte for byte against what the approved project binds.
