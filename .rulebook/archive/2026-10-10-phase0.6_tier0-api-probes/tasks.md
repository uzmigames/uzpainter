## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store

## 2. Implementation
- [x] 2.1 Write the probe instruction sequences and `parity/manifests/phase0/tier0-api-probes.json` with stable probe ids
- [x] 2.2 Set→get probes through a freshly resolved handle and after save/reopen for the properties the Phase 1 facade subset uses
- [x] 2.3 Mask-stack context probes: channel and source mode `None` rules and the errors otherwise
- [x] 2.4 Active-channel reset probe: `active_channels` assigned after `set_source`, with readback and exported output
- [x] 2.5 `set_source(None, …)` on a multichannel fill: exception class and message recorded
- [x] 2.6 `insert_*` position-rule probes and the errors they raise
- [x] 2.7 Event-order probes for create/open, save and close, with `is_busy()` and `is_in_edition_state()` transitions
- [x] 2.8 Record every probe twice (same session; after save/reopen) and admit the records to the store

## 3. Tests
- [x] 3.1 Admission check: every probe id has two recordings whose hashes are in the manifest and resolve with `uzpainter parity verify`
- [x] 3.2 Provenance check: every symbol a probe calls is documented in `python-doc`
- [x] 3.3 Guard run: no readback JSON is in the repository

## 4. Acceptance
- [x] 4.1 Acceptance (P0-TIER0, API probes): each probe golden recorded ≥ 2× and admitted

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Evidence (local oracle run, 2026-10-10, owner's machine)

- Location decision: the coordinator asked for task-specific subfolders, so the probes are nine manifests under `parity/manifests/tier0/api-probes/` (one golden each, `tier0/api-probes/<probe>`), not one `parity/manifests/phase0/tier0-api-probes.json`; fixtures under `parity/fixtures/api-probes/`.
- Painter 12.1.0 (`12.1.0+js-api.1.1.20`), started with `--enable-remote-scripting`, one session under the shared Painter lock (acquired, Painter closed, released). `python -m tools.parity.recorder.probes record <manifest>` for all nine probes: exit 0 each.
- Recordings per golden: two (`same_session`, `after_save_reopen`); `lifecycle-events` four (two cycles). Every probe output id appears in both recordings of its golden.
- Admission: `python -m tools.parity.store record parity/manifests/tier0/api-probes/<probe>.json --run <run>` exit 0 for all nine (9 golden records, 18 exported maps); `python -m tools.parity.store verify parity/manifests/tier0/api-probes` exit 0 (all available); whole-store `python -m tools.parity.store verify` exit 0.
- Guard: `python -m tools.parity.guard` with the store index: 1483 files checked, 0 blocked.
- Oracle stability (numbers only): readbacks are equal between the recordings except for values that depend on the condition (resource context of the reopened project instance; file path, name, mesh-map resource context after save). The `mask-stack` BaseColor export differs between `same_session` and `after_save_reopen` (4608 of 196608 16-bit values, max |Δ| 252); two separate runs gave the same two hashes, so the difference is deterministic. Its classification belongs to `phase0.7_tier0-stability-fits`.
- Quality gate: `python -m mypy`, `python -m ruff check .`, `python -m pytest` (616 passed). The mypy and ruff findings that remain are in `tests/parity/feasibility/` and `tools/parity/feasibility/`, which belong to sibling tasks still in progress; there are none in this task's files.
