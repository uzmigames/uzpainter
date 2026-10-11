# 54. PassThrough stays a release gap recorded through the UI, not ruled not_migratable

**Status**: accepted
**Date**: 2026-10-11
**Related Tasks**: phase1.11_compositor-blend-gaps, phase0.7_tier0-semantics-ui-cases

## Context

Item 2.3 of `phase1.11_compositor-blend-gaps` asks to record PassThrough through Painter's documented API and fit it. Otherwise it asks to record PassThrough `not_migratable` with the reason, and to ask the owner.

- **The API cannot set it.** Painter 12.1.0's python-doc lists `BlendingMode.PassThrough`, but the runtime has no such member, and a new group defaults to `Normal` (phase0.6 finding). No existing golden records the mode, so it cannot be fitted now.
- **The UI can.** Decision 029 lets an agent that holds the Painter lock set UI-only values through UI automation, with a settings sheet. `phase0.7_tier0-semantics-ui-cases` item 2.4 already scopes the PassThrough goldens, with and without masks.
- **The evaluator has a hypothesis.** The children composite into the enclosing list with their opacities scaled by the group's.
- **No current asset uses it.** No Assets3D stack in `Pipeline/` uses a PassThrough group or a `blend` key: Wand v1, Belt v5 (`retopology/waist-v5/stack-belt.json` and `stack-sash.json`), hat and staff. Tunic v10 has no stack file in `Pipeline/` yet.

The owner delegated decisions. The model panel was consulted (cx/gpt-6-astra, kimi/kimi-k3, xai/grok-4.5):

| Claim | Verdicts |
|---|---|
| C1 Do not rule PassThrough `not_migratable`: it is recordable through the UI | AGREE x2, PARTLY x1: an explicit owner scope decision could still exclude it, but API absence alone is no reason |
| C2 Keep it `release-gap` with the hypothesis implementation. The golden comes from phase0.7 ui-cases item 2.4, already scoped there. Fit and acceptance stay in phase1.11 item 2.3, which stays open | AGREE x3: state that this clarifies item 2.3's wording |
| C3 Write the exact recording spec into this task's report, with discriminating variants | AGREE x2, PARTLY x1: add multiple children at group opacity 0.5, a Normal-group control and each mask placement |
| C4 Gates whose content uses PassThrough list phase1.11 item 2.3 as a prerequisite | AGREE x3: an unchecked asset is unknown, not absent |

## Decision

1. PassThrough is not ruled `not_migratable`. It stays `release-gap` in the capability inventory, and the hypothesis implementation is unchanged.
2. This clarifies item 2.3:
   - The golden is recorded through the UI by `phase0.7_tier0-semantics-ui-cases` item 2.4 (decision 029), not through the documented API.
   - That item was already scoped in phase0.7, so nothing moves into a lower-numbered task.
   - The fit and its exact acceptance stay in phase1.11 item 2.3, which stays unchecked until the golden exists.
3. The recording spec is in §3 of `parity/reports/phase1/compositor-blend-gaps.md`. It covers:
   - multiple children, including a Multiply child over a non-trivial backdrop;
   - group opacity 0.5 and a Normal-group control;
   - each mask placement;
   - two recordings.
4. A gate whose content uses a PassThrough group lists phase1.11 item 2.3 as a prerequisite. Tunic v10 is checked when its stack exists.

## Consequences

- phase1.11 cannot be archived until the UI golden is recorded and fitted, or until the owner rules otherwise.
- phase0.7 ui-cases item 2.4 records to the spec in the phase1.11 report.
