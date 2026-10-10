## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.3_painter-oracle-recorder, phase0.5_private-oracle-store

## 2. Children
- [x] 2.1 Child accepted: phase0.6_tier0-semantics-goldens (`04-layer-stack-and-compositing.md` §9 goldens)
- [x] 2.2 Child accepted: phase0.6_tier0-defaults-templates (baking defaults, template channel sets and formats)
- [x] 2.3 Child accepted: phase0.6_tier0-api-probes (API readback and quirk probes)
- [x] 2.4 Child accepted: phase0.7_tier0-stability-fits (oracle-stability report, first `parity/semantics/*.json` fits)

## 3. Integration checks
- [x] 3.1 Every Tier 0 manifest in `parity/manifests/` lists two recordings per golden and `uzpainter parity verify` passes for all of them on the owner's machine
- [x] 3.2 The guard passes on the repository: no Tier 0 blob, readback or capture is committed, only hashes

## 4. Acceptance
- [x] 4.1 Acceptance gate (P0-TIER0): each golden recorded ≥ 2×; stability classified; fits published

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Evidence (2026-10-10, owner's machine, tree of commit `c656753`)

Full report: `parity/reports/phase0/tier0-goldens.md`.

- 1.1, 2.1-2.4: all six tasks archived (`.rulebook/archive/2026-10-10-*`). `phase0.7_tier0-semantics-ui-cases` is not a prerequisite (owner answer, 2026-10-10).
- 3.1: 59 manifests under `parity/manifests/tier0/`. Each names its private record (`golden-record`) by SHA-256. A manifest lists the per-recording map hashes (`r1-*`, `r2-*`) where the golden exports maps; for JSON-only goldens (readbacks, captures) the recordings live inside the private record. Every private record resolves in the store and passes `record_problems` with both `same_session` and `after_save_reopen` recordings: 57 records hold 2 recordings, `baking-defaults` 3, `lifecycle-events` 4. `python -m tools.parity.store verify` exit 0 (store ok); `python -m tools.parity.store verify parity/manifests` exit 0, 76 manifests, 2587 blobs available (Tier 0: 59 manifests, 2523 blobs).
- 3.2: `python -m tools.parity.guard` exit 0: store-hash rule against the store index (722 hashes), 1932 files checked, 0 blocked.
- 4.1: recorded ≥ 2× (3.1); stability classified in `parity/reports/phase0/tier0-stability.md` (53 stable, 6 unstable and not admitted as exact goldens, exception evidence in its §4, no exception proposed); 6 `parity/semantics/*.json` files with 51 entries (6 exact, 43 calibrated with residuals, 2 gaps moved to the UI-cases task); `python -m tools.parity.fit check` exit 0, every fit reproduced.
- 5.1: `parity/reports/phase0/tier0-goldens.md` (gate evidence); `docs/licensing-and-clean-room.md` §3 gains the row for the OpenEXR Python binding 3.4.8 (BSD-3-Clause, dev-only tool, not shipped), the gap reported by `phase0.7_tier0-stability-fits`.
- 5.2: `tests/parity/test_tier0_gate.py`: corpus covers every child; every manifest validates and names its private record by hash only; every golden recorded at least twice (store); a golden with one recording is not admitted (store); every listed hash verifies (store); the stability report classifies every golden.
- 5.3: `python -m mypy` (141 files, no issues); `python -m ruff check` on the new test clean (the only findings repository-wide are in another task's untracked `tools/parity/normal_convention/`); `python -m pytest tests/parity/test_tier0_gate.py` 64 passed with the store, 61 passed and 3 skipped without it; full suite 811 passed, 6 errors, all in `tests/parity/feasibility/test_recorder_procedural.py` and caused by another task's uncommitted edit to `tools/parity/recorder/painter_side.py` (`import substance_painter.event`, absent from that test's fake), not by this task; reported to that task. Guard re-run after this task's files: 1961 files checked, 0 blocked.
