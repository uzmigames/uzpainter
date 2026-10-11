# 36. Painter auto-updated to 12.1.5: 12.1.0 stays the acceptance oracle, 12.1.5 runs as a separate research envelope

**Status**: superseded
**Date**: 2026-10-11

## Context

On 2026-10-11 the oracle smoke check found Painter 12.1.5 installed: Creative Cloud replaced the executable on 2026-10-10 20:46 local, after the corpus was recorded. All 82 golden manifests are 12.1.0+js-api.1.1.20 (the recorder refuses any other build, so the corpus is homogeneous), and only 12.1.5 is installed now, so no new oracle recording is possible. Decision 001 names Painter 12.1.0 as the acceptance oracle; decision 034 prescribes canary, diff and a new envelope after a Painter update. Restoring 12.1.0 needs the owner's Creative Cloud GUI. Panel vote (cx/gpt-6-astra C, cx/gpt-5.6-sol A, kimi/kimi-k3 B-with-change equivalent to C, xai/grok-4.5 C); all four held that changing decision 001's version pin is owner-level and outside the panel's delegation. Historical context: docs/analysis/multi-model-review/.

## Decision

Painter 12.1.0 remains the acceptance oracle of decision 001; its 82 goldens, r1 targets, decision 032 records, the 61 semantics fits and the settled evaluator profile stay the acceptance basis, unchanged. Painter 12.1.5 is recorded as a separate envelope (decision 034) for research only: the recorder gains explicit per-build envelope support (12.1.0 = acceptance, 12.1.5 = research), not a bypass of its build guard; every 12.1.5 record and report is tagged with its envelope, and the verdict tooling refuses to let 12.1.5 evidence satisfy any 12.1.0 acceptance comparison or gate. First step: the 10-golden canary recorded on 12.1.5 and diffed against the 12.1.0 goldens to measure drift between builds. The stability study may run on 12.1.5 as research evidence. Switching the acceptance oracle to 12.1.5 (amending decision 001) or restoring 12.1.0 is an owner action; it is flagged in reports and blocks nothing else.

## Alternatives Considered

- A: block oracle work until the owner reinstalls 12.1.0 (rejected: indefinite block on a GUI action; remains the owner's option)
- B: adopt 12.1.5 as the acceptance oracle now (rejected: amends decision 001, outside the panel's delegation; 12.1.5 evidence cannot establish parity with 12.1.0)
- Relax the recorder's build guard (rejected: would let a second build silently become the oracle)

## Consequences

phase0.9_oracle-envelope gains per-build envelope support and the 12.1.5 canary run. New Tier-0 cases needed by the compositor work can be recorded on 12.1.5 as research but are not acceptance goldens until 12.1.0 is restored or the owner ratifies 12.1.5. Owner actions (non-blocking): disable Creative Cloud auto-update for Painter; either reinstall 12.1.0 or ratify 12.1.5 once the canary drift is known.

**Superseded by**: decision 037 (rolling Painter oracle; the owner keeps Creative Cloud auto-update on).
