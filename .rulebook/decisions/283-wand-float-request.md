# 283. The Wand float request: the Wand v1 golden replayed byte for byte, closed by a recorder export of BaseColor, Roughness, Metallic and Height as OpenEXR 32f with the same infinite padding

**Status**: accepted (the request); recording pending
**Date**: 2026-10-19
**Related Tasks**: phase1.25_pilot-wand, phase1.18_export-engine

## Context

The Wand v1 Tier 1 golden (`phase1/tier1/wand-v1`, decision 099) exports Height as PNG 16, but the document stores Height as L16F. Each PNG 16 code has several L16F preimages, so 284 of the Wand's remaining infinite-padding ring misses can only be scored as LP-consistent, not exact (decisions 277 and 281). A float export of the same document, with the same padding, removes that ambiguity. It is one more recording of the oracle, not a parity exception.

The golden's export is `painter_export.py`, a UzmiGames pipeline script run byte-unchanged (decision 099). It hard-codes PNG 16, so its float export cannot come from the script itself.

## Decision

**A new golden, `phase1/tier1/wand-v1-float`**, recorded from the request `parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase1/tier1/wand-v1-float.json`:
- **Steps 1 to 3, every Assets3D input and every applied setting are the Wand v1 golden's, byte for byte.** That covers the create, sync and export scripts, their arguments files, the stack, the 14 bitmaps, the mesh, the material library, and the Normal and AO mesh maps. They run under the same two recorder adaptations.
- **Step 4 is `substance_painter.export.export_project_textures` with `config`.** `config` is the authored repository file `parity/fixtures/tier1/wand-v1-float/export-config.json` (sha256 `3ac5935ce4d8f5c7358bdc60c4635dc946899a23572c4225b0e3c4c3911d57dd`), handled like a migration golden's export configuration (decision 194).
  - It exports BaseColor (RGB), Roughness, Metallic and Height (L) from the same document maps and channels as `painter_export.py`.
  - The format is OpenEXR 32f. Every other parameter is the script's: sizeLog2 11, `infinite` padding, no dithering, no shader parameters.
  - Each file name is the script's with the suffix `_f32`.
  - The one added setting is `export.exr.bit_depth = 32f`.
- **The recorder runs step 4 after every script export (r1, r1-repeat, r2), on the same document.** Each run writes into a fresh directory of its own (`<recording>/config/export`), behind its own fence, and is verified like a texture export.
- **The proof that it is the same document:** the run's PNG 16 maps must equal the Wand v1 golden's byte for byte, recording by recording. If they do not, the run is not admitted.

**Recorder changes (`tools/parity/recorder/script_run.py`):**
- A pipeline-script job may end with that one config export.
- A repository-file input must be that export's configuration, and a config export anywhere but last is refused.
- Two exports that write a map of the same name refuse the run.
- `export_config` and the config-export runner moved here from `migration.py`, which now calls them. The migration golden's behaviour is unchanged.
- `--pilot wand-float` writes the request. The Wand's `_tmp` arguments files are gone from Assets3D, so it runs over a staged copy of the golden's pinned inputs, which come from the private store.
- `golden-public.json` now lets the `uzmigames_pipeline_scripts` interface name that one documented export call besides `uzmigames.pipeline.run_script`.

## Recording

**Pending.** The Assets3D Painter lock was held by another session (`Claude/horse-bake`) on every check from 14:38 to 15:28 (eleven checks, about 5 minutes apart). The request was therefore committed unrecorded.

To record it, under OCIO with Painter's substance configuration, with the lock held:

```powershell
python -m tools.parity.recorder record-script parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase1/tier1/wand-v1-float.json --assets-root E:\UzmiGames\Assets3D --launch
```

Then:
1. Check the run. Every PNG 16 map of r1, r1-repeat and r2 must equal the Wand v1 golden's `<recording>-export-<map>` hash, and each `_f32` map must be identical across the three recordings.
2. Admit it with `python -m tools.parity.store record parity/envelopes/painter-12.1.5_js-api.1.1.20/manifests/phase1/tier1/wand-v1-float.json --run <run>`.
3. Delete the request.

## Consequences

- Once admitted, the Wand's Height ring and gutter can be scored exactly against the L16F values Painter exported, and so can BaseColor, Roughness and Metallic at float precision. The PNG 16 Wand golden stays the acceptance target of the Tier 1 comparison.
- No Painter pixels enter the repository. The request and the configuration are authored, and the outputs go only to the private store.
