# 101. The Phase 1 recording batch records 19 of 24 requests in Session L and is stopped before Session O

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.16_export-processing-encoders, phase1.17_export-presets, phase1.18_export-engine, phase1.20_pyapi-facade, phase1.21_pyapi-dispatcher-lifecycle, phase1.22_pyapi-cli-capabilities, phase1.25_pilot-wand

## Context

Decision 100 prepared 24 requested goldens for two Painter sessions (`parity/RECORDER.md` §11). The batch ran on 2026-10-12 on the owner's machine: Painter `12.1.5+js-api.1.1.20`, Legacy colour management (no `OCIO`, no `PAINTER_ACE_CONFIG`), documented API only, under the Assets3D Painter lock, throwaway projects only. The coordinator stopped the batch during Session L because the owner needed Painter. No recording was running when it stopped.

## Decision

Nineteen goldens are recorded (`r1` same session, `r2` after save and reopen), admitted with `python -m tools.parity.store record --run`, and their requests deleted. `store verify` of the envelope's `tier0/` and the guard pass.

| Golden | golden-record SHA-256 (prefix) | Records | r1 = r2 |
|---|---|---|---|
| `tier0/semantics/export-bit-depth` | `a646339578936fe6` | 2882 | 1436 of 1440 maps; `s3` Normal_OpenGL/DirectX at infinite padding differ |
| `tier0/semantics/export-padding` | `8d39739552997b1e` | 894 | 432 of 446 maps; the 14 passthrough maps differ |
| `tier0/semantics/export-padding-bevelled-cube` | `2e317de7a153c60d` | 370 | 172 of 184 maps; the 12 passthrough maps differ |
| `tier0/semantics/export-padding-sphere` | `615758a27598ae3f` | 354 | 164 of 176 maps; the 12 passthrough maps differ |
| `tier0/semantics/export-padding-seam-256` | `46857629937dd9e2` | 26 | all equal |
| `tier0/semantics/export-padding-seam-field-256` | `0221d0ab100687ac` | 18 | all equal |
| `tier0/semantics/export-padding-seam-1024` | `73d3130654089f96` | 26 | all equal |
| `tier0/semantics/export-padding-seam-field-1024` | `70c399ad26bf4121` | 18 | all equal |
| `tier0/semantics/export-alpha-layouts` | `1428d5769e8ad20a` | 18 | all equal |
| `tier0/semantics/export-resize` | `6c89b1095a61dc29` | 1044 | all equal |
| `tier0/semantics/export-dither` | `3e4eec9fcd56624b` | 578 | all equal |
| `tier0/semantics/export-ocio-encode-legacy` | `ce9a70b4272ca354` | 258 | 123 of 128 maps; `s5` basecolor at infinite padding (PNG 8, PNG 16, EXR 32f) and two `s5` export-probe maps differ |
| `tier0/api-probes/phase1-delete-node` | `85e06070610d3ae3` | 4 | export equal |
| `tier0/api-probes/phase1-resource-update` | `20cde05589edabdf` | 4 | export equal |
| `tier0/api-probes/phase1-save-modes` | `56ec47a22951c82a` | 4 | export equal |
| `tier0/api-probes/phase1-create-settings` | `23eea16fe663a4ac` | 4 | export equal |
| `tier0/api-probes/phase1-reload-mesh` | `ce7a4c2f59e36a6d` | 14 | exports equal |
| `tier0/api-probes/phase1-reload-resources` | `4ea41f901841f58f` | 4 | export equal |
| `tier0/api-probes/phase1-execute-when-not-busy` | `d3bedea4eb97f30a` | 4 | export equal |

Every same-session repeat of an export step is identical in both recordings of every golden. The r1/r2 differences are all save-and-reopen differences (decision 032). In the probes, only readbacks differ: events, file paths, resource contexts and texture-set listings that depend on the condition. Comparison: exported maps by SHA-256, readbacks as canonical JSON with the per-project resource context (`resource://projectN/`) normalised.

Admitted Tier 0 goldens join `recording_requests.ADMITTED`, and the generator plans their manifests under `manifests/`. `current.api_goldens` cannot take them, because their inputs are the request fixtures. `tests/parity/recorder/test_api_probes_phase1.py` reads a probe from its admitted manifest once its request is gone.

Not recorded. The requests stay under `requests/`, to resume in a later session:

1. `tier0/semantics/export-presets-legacy` (Session L). Painter crashed (process exit, crash dump `Adobe Substance 3D Painter.exe.87156.dmp`) in r1 at step 40: `list_project_textures` / export of the inline five-map preset at `sizeLog2` 7 (`probe-presets-bevelled-cube-inline-five-map-7`). Four of five maps were written, and the crash came while it wrote `uzp_staff_Normal`. Step 39, the same preset at `sizeLog2` 8, completed. It was not retried, so it is not known whether the crash reproduces. Resume by recording it once more in a fresh Legacy session. If it crashes again, the crash is the observation: split step 40 out under a new request name.
2. `tier0/api-probes/phase1-engine-computations` (Session L, last; may hang by design).
3. `tier0/semantics/export-ocio-encode`, `tier0/semantics/export-presets-ocio` (Session O).
4. `phase1/tier1/wand-v1` (Session O, `record-script --assets-root E:\UzmiGames\Assets3D`).

`parity/reports/phase0/tier0-stability.md` is regenerated (`python -m tools.parity.fit run`; 139 goldens, 99 stable, 40 unstable). Stable and exact: `export-alpha-layouts`, `export-dither`, `export-resize` and the four seam goldens. Unstable under save and reopen (`r1` stays the exact target): `export-bit-depth`, `export-padding`, `export-padding-bevelled-cube`, `export-padding-sphere`, `export-ocio-encode-legacy` and the seven probes. That run also re-stamped five `parity/semantics/*.json` files with build `12.1.5`, and nothing else changed in them. Those edits were not kept: republishing a fit under the new envelope is its owner's `fit check` step (decision 037).

## Alternatives Considered

- Retry `export-presets-legacy` at once: rejected. The owner needed Painter.

## Consequences

### Positive
- phase1.16 (R1-R4 and R-090: bit depth, padding, alpha layouts, resize, dither), phase1.20 (R5's Legacy twin) and phase1.21/1.22 (seven of the eight R10 probes) have their recordings.

### Negative
- phase1.17 (R6-R8), R5 under OCIO, the engine-computations probe and phase1.25 (R9) still wait for a Painter session.

## Follow-ups
- Resume the five requests above in the order of `parity/RECORDER.md` §11.
- Regenerate `parity/reports/phase0/tier0-stability.md` after the remaining recordings.
