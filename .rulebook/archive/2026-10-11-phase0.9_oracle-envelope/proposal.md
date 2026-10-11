# Proposal: phase0.9_oracle-envelope

## Why
Painter differs from itself on 6 of 59 Tier 0 goldens across save/reopen (`parity/reports/phase0/tier0-stability.md`), and no golden records the GPU, driver, OS build or colour configuration it was recorded under, so a driver or Painter update can move the target without anyone noticing. Decision 032 settles save/reopen instability (the same-session recording r1 is the exact target), but variance across fresh Painter processes and across environments is unmeasured. All four models of the 2026-10-11 review panel named this the top risk the project analysis missed (`docs/analysis/multi-model-review/`). Decision 034 defines the envelope and the study; this task implements it (`docs/dag.md` P0-ORACLE-ENVELOPE, joins G0).

## What Changes
- Golden environment record: Painter build string, GPU model, driver version, OS build, colour-configuration hash, recorder version, and for Iray references the operator id. The recorder writes it into every private record and its public hash into the public manifest; schemas in `parity/schema/` gain the field; existing goldens get the record of the environment they were recorded under where it is known, and `unknown` fields otherwise.
- Comparison rule: UzPainter-to-golden comparisons stay offline and valid against the golden's recorded envelope; oracle re-recording and oracle-to-golden comparisons require matching envelopes and report `out_of_envelope` otherwise (never `pass` or `fail`).
- Stability study: the Tier 0 corpus re-recorded 5 times per golden (2 same session, 2 after save/reopen, 1 in a freshly started Painter process) through the recorder's documented remote-scripting path; per-golden self-variance published (numbers and hashes only); fresh-process instability classified apart from save/reopen instability. Fresh-process-unstable goldens follow decision 032's rule (r1 exact target, residuals published) and get prepared register entries that stay unapproved until the owner approves them (decision 017).
- Canary: a fixed 10-golden subset and the procedure that re-records and diffs it after a GPU, driver, OS or Painter update; any non-zero difference re-records the affected goldens under a new envelope, keeping the originals, their r1 targets and their 032 records.
- Report `parity/reports/phase0/oracle-envelope.md`.

## Dependencies
- Prerequisites: `phase0.8_tier0-goldens` (P0-TIER0, archived), `phase0.3_painter-oracle-recorder` (P0-RECORDER), `phase0.5_private-oracle-store` (P0-STORE).
- Joins: `phase0.10_gate-g0` (G0). Decisions 017, 032, 034.
- Runs on the owner's machine with Painter 12.1.0 started with `--enable-remote-scripting` (`parity/RECORDER.md`); texture goldens need no operator.

## Acceptance
Envelope recorded on every admitted golden; stability study published and run before any further calibration of `calibrated` fits; canary procedure tested (`docs/dag.md` P0-ORACLE-ENVELOPE; decision 034).

## Impact
- Affected specs: parity
- Affected code: `tools/parity/recorder/`, `tools/parity/store`, `tools/parity/verdict.py`, `parity/schema/`, `parity/CONTRACT.md` §6
- Breaking change: NO (new optional field on existing goldens; `out_of_envelope` is a new outcome for oracle-side comparisons only)
- User benefit: a parity verdict always says which oracle environment it was measured against, and an environment change can no longer move the target silently
