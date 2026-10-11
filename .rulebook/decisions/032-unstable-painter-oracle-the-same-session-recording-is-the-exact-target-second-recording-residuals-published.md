# 32. Unstable Painter oracle: the same-session recording is the exact target, second-recording residuals published

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.9_compositor-quantisation-profile

## Context

Owner, 2026-10-11, during phase1.9_compositor-quantisation-profile: quantisation-thirds and blend-inputs s2 are unstable in Painter (classified in parity/reports/phase0/tier0-stability.md); the settled profile painter-12.1-isolated-linear matches r1 exactly. CONTRACT treated unstable goldens as blocked; this decision is the owner-approved exception under decision 017.

## Decision

When Painter itself is unstable for a golden (its same-session recording r1 and its after-save/reopen recording r2 differ), the exact target is r1. UzPainter must match r1 exactly; the r1-vs-r2 differences and UzPainter's residuals against r2 are published as evidence. Each such golden gets an entry in parity/exceptions.json naming this decision as its owner approval.

## Consequences

Unstable goldens no longer block gates when r1 matches exactly and the register entry exists. Any remaining r1 mismatch is still a divergence. Separately (owner, same day): residuals with no shipped consumer, such as RGB32F channels off by 2^-25..2^-24, go to their own follow-up task, stay visible and are never counted as passes.
