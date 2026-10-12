# 80. Two deterministic save-and-reopen divergences of the decision 077 recordings get decision-032 exception entries EXC-004 and EXC-005

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.12_compositor-height-normal

## Context

Two of the ten recordings of decision 077 differ between r1 (same session) and r2 (after save and reopen), deterministically (a second Painter process reproduced both recordings map for map):

- `tier0/semantics/height-normal-channel-coverage` s2 (normal-a on the Normal channel at opacity 1 under a Black mask with a mask-codes fill), domain `tier0/height-normal/combination`: against the evaluator, which equals r1 on every map (decision 079), r2 differs on Normal_OpenGL 142 764 and Normal_DirectX 142 862 of 196 608 values (max 61 codes, per-map mean at most 4.62893), and on the Normal export 114 266 values (max 2^-10). No coverage variant explains r2 (round to nearest half 110 508 values off, 8-bit coverage 122 174, the unquantised coverage 110 675).
- `tier0/semantics/height-normal-resolution-2048` s2 (opacity 0.25), domain `tier0/height-normal/resolution`: r2 differs on 4 and 5 values of the virtual maps by one code; r2 equals the stencils on the stored Height (half toward zero; the subnormal halves near 0 truncated) instead of the read-out before the write rule.

Decision 032 (owner-approved) makes r1 the exact target of an unstable golden and requires "an entry in parity/exceptions.json naming this decision as its owner approval"; EXC-003 is the precedent for two earlier height-normal sets (domain `tier0/height-normal/method`). Decision 077 left these two goldens outside every exception, as phase1.12's to propose.

The model panel ruled on 2026-10-11 under the owner's delegation (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5), claim C6 of the decision 079 dossier:

| Claim | Verdicts |
|---|---|
| EXC-004 (`tier0/height-normal/combination`) and EXC-005 (`tier0/height-normal/resolution`) following EXC-003 exactly: r1 exact, only r2 comparisons bounded by the published r2 residuals, decision_id 032, approved_by owner, the defect-detection test extended, flagged for the owner's review; the alternative leaves r2 uncovered and the goldens blocked | AGREE x3: decision 032 authorises per-golden r2 entries; pin the counts, maxima, units and record hashes; test rejection of r1 drift and out-of-bound r2 drift; the owner-review flag does not replace the recorded approval |

## Decision

1. `parity/exceptions.json` gains EXC-004 (domain `tier0/height-normal/combination`; bounds max |delta| 61, mean 4.629, differing 72.67 %) and EXC-005 (domain `tier0/height-normal/resolution`; bounds max |delta| 1, differing count 5), basis `oracle_instability`, the private golden records' hashes as evidence, decision_id 032, approved_by owner, approved_on 2026-10-11, with the EXC-003 defect-detection test.
2. The bounds are the published r2 residuals of the entries `height-normal-coverage-save-reopen-divergence` and `height-normal-resolution-save-reopen-divergence` of `parity/semantics/height-to-normal.json`; every comparison against r1 stays exact.
3. `tests/parity/test_verdict.py` covers both entries: r1 equality passes through the entry, every injected defect fails, the exact target holds within the current envelope.
4. Both entries are flagged for the owner's review in the task report and the hand-off: they rest on decision 032's standing approval, not on a new owner signature.

## Alternatives Considered

- Leaving the r2 comparisons uncovered (rejected: the goldens stay blocked on a known Painter save-and-reopen effect without adding evidence).
- One entry for both domains (rejected: an entry selects one domain; the bounds differ by two orders of magnitude).

## Consequences

The decision-077 goldens pass their gates on r1 exactness with r2 bounded; any r1 mismatch is still a divergence. The owner may withdraw either entry, which would block only the r2 comparisons of the two sets.
