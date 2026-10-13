# 180. Painter batch D admits Session O, the wand R9, export-presets-legacy and four API probes, and stops the dense sRGB probe at the time cap

**Status**: accepted
**Date**: 2026-10-12
**Related Tasks**: phase1.15_compositor-colour-fits, phase1.25_pilot-wand

## Context

The queue held the OCIO Session O goldens (decisions 100 and 101), R9 (decisions 099 and 144), `export-presets-legacy` (it crashed Painter at step 40 in decision 101) and the authored API probes P20-B, P22-A, P22-C, P23-A and R10 engine computations (decisions 107, 111, 113 and 157). They were recorded on 2026-10-12 in Painter `12.1.5+js-api.1.1.20`:

- under the Assets3D Painter lock, on throwaway projects only, through the documented API;
- in two sessions:
  - Session O ran 21:59-22:00, with `OCIO` set to Painter's `resources\ocio\substance\config.ocio`. `envelope check` reported `other_environment`, because the colour configuration hash is part of the environment.
  - Session L ran 22:00-22:18, Legacy, with no `OCIO` and no `PAINTER_ACE_CONFIG`. `envelope check` reported `current`.

Painter was open for about 19 minutes in all, under the 40-minute cap. It was closed after each session, and the lock was released. Painter did not crash.

## Decision

Eight goldens were recorded and admitted with `python -m tools.parity.store record --run`. Their requests were deleted, and the three Tier 0 semantics goldens joined `recording_requests.ADMITTED`. `store verify` of the envelope's manifests and `python -m tools.parity.tier0_semantics check` pass.

| Golden | Session | golden-record SHA-256 (prefix) | Stability |
|---|---|---|---|
| `tier0/semantics/export-ocio-encode` | O | `7f6acce36a4fbaf0` | unstable: s5 BaseColor (sRGB bitmap in a group masked by grey A) differs r1 vs r2 in PNG 16, PNG 8 and OpenEXR 32f, the s5 pattern of `srgb-bitmap-variants-v2` |
| `tier0/semantics/export-presets-ocio` | O | `9e84c5d35661be30` | unstable through readbacks only (two probe `list` readbacks); every map r1 = r2 |
| `phase1/tier1/wand-v1` (R9) | O | `9ff068c77c2c9537` | stable: the five maps are byte-identical in `r1`, `r1-repeat` and `r2`; only the export directory in the script result differs |
| `tier0/semantics/export-presets-legacy` | L | `db235dd2cfedc0d9` | unstable through readbacks only (two probe `list` readbacks); every map r1 = r2 |
| `tier0/api-probes/phase1-mesh-map-update` (P22-A) | L | `4dc94157bb11e546` | unstable through `start/events` only |
| `tier0/api-probes/phase1-restored-values` (P22-C) | L | `0071a5c35e6e0bb9` | unstable through `start/events` only |
| `tier0/api-probes/phase1-save-as-existing` (P23-A) | L | `618987c7114b385f` | unstable through readbacks (`s8/file_path`, `s9/needs_saving`, `start/events`) |
| `tier0/api-probes/phase1-engine-computations` (R10) | L | `4acaba2821b078f6` | unstable through `start/events` only |

The regenerated `parity/reports/phase0/tier0-stability.md` (no fits run) covers 192 goldens: 133 stable and 59 unstable. Every probe's BaseColor export is equal in r1 and r2.

**Observations.**

- **`export-presets-legacy` did not crash.** Step 40 is the inline five-map preset at `sizeLog2` 7. This time it listed and exported all five maps with status `Success`. The crash of decision 101 did not reproduce in a fresh session, so no split request is needed.
- **R10 did not hang.** With engine computations disabled, the export finished with `Success` and wrote its file. That file is identical in both recordings.
- **P22-C.** After `save_as`, `needs_saving()` turns true after each edit and false again once the saved value is restored, in both recordings. This holds for opacity, visibility and blending. A rename followed by an opacity edit, with both reverted, also ends false.
- **P23-A.** `save_as` onto an existing `.spp` raised nothing in either recording.
- **P22-A.** After `update_layer_stack_resource(mask_left_half -> ao_white)`, the AO mesh map names `ao_white`.

**Not recorded: `tier0/api-probes/phase1-srgb-uniform-decode` (P20-B).**

- The request has 645 steps: 320 `set_source` and 320 `get_source`. The observed-probe recorder runs its `s<n>/states` polls after every step, so each step takes about 1.6 s.
- At 22:14, 13 minutes into `r1`, the fill held the grey 242/255, which is about step 488. The recorder process showed no CPU activity and had one connection to Painter open.
- It was stopped at that point to keep within the cap. Painter still answered, so the throwaway project was closed through `project.close()`, and the session continued.
- At this rate the probe needs about 35 minutes. That is more than one capped Painter window, so it was not retried. Nothing was written, and its request stays.

## Consequences

### Positive
- phase1.15 item 2.3 now has its Session O goldens, and phase1.25 now has the admitted R9 golden. `tests/parity/tier1/wand_v1` no longer skips for want of a golden. It is a GPU run and belongs to the coordinator's batch.
- The wand's request path changed to the admitted manifest in `tests/adapters/assets3d/wand.py`, `tests/parity/recorder/test_script_run.py` and `tests/parity/tier1/test_tier1_compare.py`.

### Negative
- P20-B (decision 107) is still unrecorded.

## Follow-ups
- P20-B, owned by the recording queue: one of the following.
  - Record it alone in a Painter window of at least 40 minutes.
  - Re-author it as four requests of 64 colours each, with each request under 10 minutes.
- phase1.15 owner: fit OCIO against `export-ocio-encode` and `export-presets-ocio` (item 2.3). s5 is unstable, so it is not an exact target.
- phase1.25 owner: run the Tier 1 wand comparison against the admitted R9 golden.
