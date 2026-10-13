# 198. Painter batch E admits the OCIO twin of P20-B, R-132-D, colour-fits 2.5, the L8 export, P20-A, the held-out minification and nine host probes

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.15_compositor-colour-fits

## Context

The queue held the requests of decisions 188 and 189 (RECORDER.md §11.4). They were recorded on 2026-10-12/13 in Painter `12.1.5+js-api.1.1.20`:

- under the Assets3D Painter lock, on throwaway projects only, through the documented API;
- in two sessions, Session O first because P20-B's OCIO twin unblocks phase1.15 item 2.6:
  - Session O ran 23:25-00:01, with `OCIO` set to Painter's `resources\ocio\substance\config.ocio`. `envelope check` reported `other_environment` (the colour configuration hash is part of the environment), as in decision 180.
  - Session L ran 00:02-00:09, Legacy, with no `OCIO` and no `PAINTER_ACE_CONFIG`. `envelope check` reported `current`.

Painter was open for about 44 minutes in all, under the 45-minute cap. A guard started a golden only when its estimated duration fitted before the cap. Painter was closed after each session, and the lock was released. Painter did not crash, and no run was void or refused.

## Decision

Nineteen goldens were recorded (`r1` same session, `r2` after save and reopen) and admitted with `python -m tools.parity.store record --run`. Their requests were deleted, and the four Tier 0 semantics goldens joined `recording_requests.ADMITTED`. `store verify` of the envelope's `tier0` manifests and `python -m tools.parity.tier0_semantics check` pass.

| Golden | Session | golden-record SHA-256 (prefix) | Stability |
|---|---|---|---|
| `tier0/api-probes/phase1-srgb-uniform-decode-ocio-part1` | O | `6e5c73840e206bba` | unstable through `start/events` only; 482 of 483 readbacks and the BaseColor export equal r1 vs r2 |
| `tier0/api-probes/phase1-srgb-uniform-decode-ocio-part2` | O | `fc562cc69f6448d5` | as part 1 |
| `tier0/api-probes/phase1-srgb-uniform-decode-ocio-part3` | O | `c6e968f8c717c93d` | as part 1 |
| `tier0/api-probes/phase1-srgb-uniform-decode-ocio-part4` | O | `f0fe7b217735f9bb` | as part 1 |
| `tier0/api-probes/phase1-display-ocio` (R-132-D) | O | `f3e79d93fb59f0f2` | unstable through readbacks (environment resource, default camera, export `files`, `needs_saving`, events) |
| `tier0/semantics/srgb-bitmap-minification` (colour-fits 2.5) | L | `6fe1a6e02cd2f846` | stable |
| `tier0/semantics/export-l8-material` (decision 169) | L | `eddbad97c8be3151` | stable |
| `tier0/api-probes/phase1-fill-channel-defaults` (P20-A) | L | `c766a53a0c7cebbf` | unstable through `s49/states`, `s50/states` and `start/events`; all five exported maps equal r1 vs r2 |
| `tier0/semantics/resample-uv-heldout-128px` | L | `3659e58521a49db8` | stable |
| `tier0/semantics/resample-uv-heldout-32px` | L | `b767d687072413b7` | stable |
| `tier0/api-probes/phase1-create-default-paths` (P21-B) | L | `7956f1ee0ac0a46b` | unstable through readbacks (file path, `needs_saving`, save events) |
| `tier0/api-probes/phase1-create-mesh-maps` (P21-A) | L | `76e6606258927061` | unstable through `start/events` only |
| `tier0/api-probes/phase1-create-open-timing` (P21-F) | L | `ef4c4453dec55434` | unstable through `thread_polls` (the timing itself) |
| `tier0/api-probes/phase1-close-without-saving` (P21-G) | L | `c40252913d960628` | unstable through `s13/file_path` and `start/events` |
| `tier0/api-probes/phase1-shelves` (P21-D) | L | `9d2c9f236422c5cb` | unstable through `start/events` only |
| `tier0/api-probes/phase1-default-camera-plane` (R-132-A) | L | `abc545251e7cfaaa` | unstable through `start/events` only |
| `tier0/api-probes/phase1-default-camera-sphere` (R-132-A) | L | `30d159f2a5c5551d` | unstable through `start/events` only |
| `tier0/api-probes/phase1-default-camera-bevelled-cube` (R-132-A) | L | `b853a436f8f92302` | unstable through `start/events` only |
| `tier0/api-probes/phase1-export-preset-search` (R-095 P7) | L | `d6b9e35180b6f818` | unstable through `start/events` only |

The regenerated `parity/reports/phase0/tier0-stability.md` (no fits run) covers 211 goldens: 137 stable and 74 unstable.

The held-out goldens `resample-uv-heldout-128px` and `-32px` are admitted only (decision 084 item 5). No fit names them: every fit module names its goldens explicitly, and `resample` reads only `semantics/resample-uv`. The stability report lists them as evidence for the open BilinearHQ kernel item, which is not a fit.

## Consequences

### Positive
- phase1.15 item 2.6 has its OCIO P20-B goldens, and the Wand pilot can proceed on them.
- Colour-fits 2.5, the L8 material export (decision 169), P20-A, R-132-A and R-132-D, R-095 P7 and P21-A, B, D, F and G are recorded.

### Negative
- These requests were not recorded because the cap was reached. Each request stays:
  - P20-B Legacy, `phase1-srgb-uniform-decode-part1..4`: about 8.5 minutes each, so they need a window of their own.
  - P21-C, `phase1-texture-throttling`: it needs a fresh Legacy session, and Session L had already run scripts.
  - P21-E, `phase1-layer-stack-events`.
  - R-132-B, `phase1-camera-coupling`.

## Follow-ups
- The recording queue's next Painter window, in a fresh Legacy session:
  - `phase1-texture-throttling` first;
  - then `phase1-layer-stack-events` and `phase1-camera-coupling`;
  - then `phase1-srgb-uniform-decode-part1..4`, about 35 minutes. This may need two windows.
- phase1.15 owner: fit item 2.6 against the OCIO parts, and item 2.5 against `srgb-bitmap-minification`.
