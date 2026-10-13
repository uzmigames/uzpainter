# 205. Painter batch F admits the Legacy P20-B parts, P21-C, P21-E and R-132-B, and every §11.4 request is recorded

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.15_compositor-colour-fits

## Context

Decision 198 left four §11.4 requests open (RECORDER.md §11.4): the four Legacy P20-B parts, `phase1-texture-throttling` (P21-C, first in a fresh session), `phase1-layer-stack-events` (P21-E) and `phase1-camera-coupling` (R-132-B). The queue also held the Tunic migration golden `phase2/tier1/tunic-v10` (Session O, decision 194) for any time left.

The recordings ran on 2026-10-13 in Painter `12.1.5+js-api.1.1.20`:

- under the Assets3D Painter lock, on throwaway projects only, through the documented API;
- in Legacy sessions, with no `OCIO` and no `PAINTER_ACE_CONFIG`. `envelope check` reported `current` before each session.

A guard started a golden only when its estimated duration fitted before the 45-minute cap, counted from the first launch (00:24:58).

- **Session 1** (00:24:58-00:26:16). `phase1-texture-throttling` was recorded first in the fresh process. Painter then crashed during the first attempt at `phase1-layer-stack-events`:
  - It happened while the recorder polled `probe_state` during the step observations of r1.
  - The fault was in `ucrtbase.dll`, exception `0xc0000409`, a fast-fail abort. Windows Error Reporting saved the report.
  - The goldens queued after it failed to connect and wrote nothing.
- **Session 2** (00:28:03-01:08:20), in a new process. It recorded `phase1-camera-coupling`, the four P20-B parts (about 8.6 minutes each) and then the single retry of `phase1-layer-stack-events`. The retry recorded without a crash.

Painter was open for about 42 minutes, and the cap was 45. Painter was closed and the lock released at the end. The Tunic migration golden was not started. It needs Painter restarted under OCIO, and the time left after the Legacy work was too short to open, export and reopen a 4K project.

## Decision

Seven goldens were recorded (`r1` same session, `r2` after save and reopen) and admitted with `python -m tools.parity.store record --run`. Their requests were deleted. `store verify` of the envelope's `tier0` manifests and `python -m tools.parity.tier0_semantics check` pass.

| Golden | golden-record SHA-256 (prefix) | Stability |
|---|---|---|
| `tier0/api-probes/phase1-texture-throttling` (P21-C) | `37e499ad4702f3e0` | unstable through `start/events` only; 4 of 5 readbacks equal r1 vs r2 |
| `tier0/api-probes/phase1-camera-coupling` (R-132-B) | `bf0acda403a4c9fc` | unstable through readbacks: 66 of 224 differ r1 vs r2 (`get_default_camera` and `events` steps) |
| `tier0/api-probes/phase1-srgb-uniform-decode-part1` (P20-B) | `9445717a57f68256` | unstable through `start/events` only; 482 of 483 readbacks and the BaseColor export equal r1 vs r2 |
| `tier0/api-probes/phase1-srgb-uniform-decode-part2` (P20-B) | `91c8c6432c565b62` | as part 1 |
| `tier0/api-probes/phase1-srgb-uniform-decode-part3` (P20-B) | `4fcc58963bd1d6db` | as part 1 |
| `tier0/api-probes/phase1-srgb-uniform-decode-part4` (P20-B) | `a5d4864a2c82881b` | as part 1 |
| `tier0/api-probes/phase1-layer-stack-events` (P21-E) | `996ce966726e231d` | unstable through `s19/events`, `s30/set_parameters` and `start/events` |

The regenerated `parity/reports/phase0/tier0-stability.md` (no fits run) covers 218 goldens: 137 stable and 81 unstable.

The crash is recorded as an observation, not as a property of P21-E. The same request recorded cleanly in a new process. The only difference was that the throttling probe had not run in that process first.

## Consequences

### Positive
- P20-B has both its Legacy and its OCIO goldens (decision 198), so phase1.15 can fit the dense sRGB decode in both colour modes.
- P21-C, P21-E and R-132-B are recorded. Every §11.4 request is now recorded.

### Negative
- One crash: a probe sequence that runs `phase1-texture-throttling` and then `phase1-layer-stack-events` in one process crashed Painter once. It was not reproduced. The one retry, in a new process without the throttling probe before it, recorded.
- The Tunic migration golden is still open.

## Follow-ups
- Next Painter window: Session O (OCIO) for `phase2/tier1/tunic-v10` alone:
  - `python -m tools.parity.recorder record-migration parity/envelopes/painter-12.1.5_js-api.1.1.20/requests/phase2/tier1/tunic-v10.json --assets-root E:\UzmiGames\Assets3D`
  - Watch for a Painter dialog on open, and for the project opening Legacy instead of OCIO.
- phase1.15 owner: fit P20-B Legacy against `phase1-srgb-uniform-decode-part1..4`.
- A later batch that runs P21-C in a session before other probes should expect a possible crash on the next probe, and restart Painter between them.
