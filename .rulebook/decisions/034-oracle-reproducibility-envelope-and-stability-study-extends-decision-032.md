# 34. Oracle reproducibility envelope and stability study (extends decision 032)

**Status**: accepted
**Date**: 2026-10-11

## Context

All four reviewing models named oracle self-instability and an undefined reproducibility envelope as the top risk the analysis missed: Painter differs from itself on 6/59 Tier-0 goldens across save/reopen, and nothing records which GPU, driver or OS build a golden was made under, so a driver or Painter update can silently move the target. Decision 032 already makes the same-session recording r1 the exact target for save/reopen instability. Decided by the model panel under the owner's delegation of 2026-10-11 (4/4 ACCEPT-WITH-CHANGE, changes merged). Analysis: docs/analysis/multi-model-review/.

## Decision

(a) Envelope. Every admitted golden carries an environment record: Painter build string, GPU model, driver version, OS build, colour-configuration hash, recorder version, and for Iray references the operator id. UzPainter-to-golden comparisons are offline and valid against the golden's recorded envelope; UzPainter's own machine need not match it. Envelopes must match only for oracle re-recording and oracle-to-golden comparisons. (b) Stability study. A one-off study re-records the Tier-0 corpus 5 times per golden (2 same-session, 2 after save/reopen, 1 in a freshly started Painter process) and publishes per-golden self-variance, classifying save/reopen instability (decision 032) separately from fresh-process instability. (c) Fresh-process instability follows 032's rule: the same-session r1 stays the exact target, UzPainter must match it exactly, the other residuals are published; no averaging, no tolerance, no silent target replacement. Its register entries are prepared with this evidence and stay unapproved (outcome blocked) until the owner approves them, as decision 017 requires. (d) Canary. After any GPU, driver, OS or Painter update, a 10-golden canary subset is re-recorded and diffed; any non-zero difference re-records the affected goldens under a new envelope, keeping the originals, their r1 targets and their 032 records. (e) The study runs before any further calibration of `calibrated` fits, and is a Phase-0 work package (P0-ORACLE-ENVELOPE) joined to G0.

## Alternatives Considered

- Average repeated recordings into a target (rejected: violates 017 exact equality)
- Tolerance band from self-variance (rejected: 017 forbids preset tolerances)
- Require the live oracle environment to match for every comparison (rejected: would invalidate the corpus after every driver update)
- Report-only study with no gate (rejected: envelope re-validation must block, not inform)

## Consequences

New task phase0.9_oracle-envelope (P0-ORACLE-ENVELOPE) joins G0. The study is unattended: the recorder drives Painter through its documented remote-scripting endpoint; it needs Painter 12.1.0 running on the owner's machine with --enable-remote-scripting. Owner signature remains required only for the register entries of fresh-process-unstable goldens. Schema work: golden metadata gains the environment record.
