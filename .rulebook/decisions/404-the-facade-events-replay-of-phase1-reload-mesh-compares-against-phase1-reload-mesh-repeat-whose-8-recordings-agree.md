# 404. The facade-events replay of phase1-reload-mesh compares against phase1-reload-mesh-repeat, whose 8 recordings agree

**Status**: accepted
**Date**: 2026-11-08
**Related Tasks**: phase1.26_gate-g1, phase1.24_python-api-facade

## Context

Gate G1 (`parity/reports/phase1/gate-g1.md` §9.1) kept `tests/python/test_pyapi_lifecycle_tier0.py::test_observed_probe_events_equal_painter[phase1-reload-mesh]` red: the 12.2.0 golden `tier0/api-probes/phase1-reload-mesh` holds, in r1 only, one asynchronous `LayerStacksModelDataChanged` at s9 and one at s11, with extra polled states there. Painter 12.1.5 and the facade deliver that event only during s3 and s6.

`2504cdf8` recorded `tier0/api-probes/phase1-reload-mesh-repeat`, a golden with the same inputs, instruction sequence and settings (equal by value to the original's manifest fields), four times on 2026-11-08: three times in one Legacy session (no prefix, `repeat2-`, `repeat3-`) and once first in a fresh session (`repeat4-`). Measured on the private store, the compared outputs (every `/events` output but `start/events`, and the `file_path` and `needs_saving` readbacks):

- the 4 `same_session` recordings are equal to each other, and so are the 4 `after_save_reopen` ones, byte for byte, before any normalisation;
- against them the original golden differs only at `s9/events` and `s11/events` of r1; its r2 is equal.

So the original's s8 `reload_mesh` ran past the settle window of that one recording, and its late deliveries landed in s9 and s11: a recording race, not Painter's behaviour for this sequence.

## Decision

1. `COMPARED_GOLDEN` in `test_pyapi_lifecycle_tier0.py` maps a probe to the golden its replay compares against when that is not its own: `phase1-reload-mesh` -> `phase1-reload-mesh-repeat`. The replay stages that golden's inputs and replays its steps, and loads it with `golden_record(..., repeats=True)`, so all 8 recordings are expected.
2. The facade must equal **every** recording of a condition, each output exactly, as before: the test now keeps the outputs of each recording apart (condition -> recording id -> outputs) instead of letting the last recording of a condition overwrite the others. A golden with one recording per condition is compared as before. No output, normalisation or exclusion changed.
3. The original golden stays admitted in the store and the manifest tree as the evidence of the race; nothing is deleted or relabelled.
4. The trace entry `facade-events/phase1-reload-mesh` names the compared golden, `tier0/api-probes/phase1-reload-mesh-repeat`, and was regenerated under decision 112 (`UZP_UPDATE_TIER0_TRACE=1`). Audit (decision 403 rules): no symbol gone; two added, `substance_painter.event.BusyStatusChanged.busy` and `substance_painter.layerstack.UVProjectionParams.uv_transformation`. Both are reads decision 403 item 1 audited as compared (the recorder's event-callback log and the projection-parameter serialisation) and both are already in every other `facade-events/phase1-*` entry; this entry had missed them only because it failed before the regeneration of decision 403.

## Alternatives Considered

- **Excluding s9/s11 or dropping LayerStacksModelDataChanged from the comparison.** Rejected: it weakens an equality rule, and the repeated recordings show the outputs are deterministic.
- **Replacing the original golden's records.** Rejected: a store entry is never rewritten, and the race is evidence worth keeping.
- **Comparing against both goldens.** Rejected: the original r1 disagrees with 4 later recordings of the same sequence; requiring it would demand the race.

## Consequences

- `test_observed_probe_events_equal_painter[phase1-reload-mesh]` passes (2026-11-08, 1 passed).
- A later probe whose golden is shown racy by repeated recordings uses the same map, with its own decision.
