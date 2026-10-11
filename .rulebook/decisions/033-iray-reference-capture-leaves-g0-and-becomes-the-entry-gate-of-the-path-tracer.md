# 33. Iray reference capture leaves G0 and becomes the entry gate of the path tracer

**Status**: accepted
**Date**: 2026-10-11

## Context

P0-FEAS-RENDER (Iray capture procedure and references) joins G0 in docs/dag.md, and G0 -> G1, but no Phase-1/2 work node depends on it; its only consumer is P3-PATHTRACER. 10 of its 14 settings rows need the owner at Painter's panels (parity/reports/phase0/iray-capture-procedure.md), so it holds the whole gate chain on owner time while blocking no code. Decided by the model panel under the owner's delegation of 2026-10-11 (panel: cx/gpt-6-astra, cx/gpt-5.6-sol, kimi/kimi-k3, xai/grok-4.5 via 9router; review 2 ACCEPT, 2 ACCEPT-WITH-CHANGE, changes merged). Analysis: docs/analysis/multi-model-review/.

## Decision

Remove the edge P0-FEAS-RENDER -> G0. P0-FEAS-RENDER stays a Phase-0 work package and is the sole entry gate of P3-PATHTRACER: no path-tracer implementation task starts before it is accepted. Its acceptance keeps every existing criterion (every settings row answered with evidence, capture procedure qualified, references admitted with their noise floor) and adds a reproducibility probe: one trivial Iray scene captured repeatedly, with pixel equality, per-setting observability and the measured variance published. The probe does not require pixel equality (decision 017 already routes Tier 3 through the noise floor and owner exceptions), and publishing it alone never unlocks the path tracer. G0's other joins are unchanged.

## Alternatives Considered

- Keep Iray in G0 (rejected: blocks G1 on owner panel time while no Phase-1/2 node needs it)
- Drop the feasibility check entirely (rejected: path-tracer investment needs a measured go/no-go first)
- Require pixel-equal Iray repeats for acceptance (rejected: Iray is stochastic with no exposed seed; contradicts CONTRACT 4.1)

## Consequences

G0 no longer waits for owner time at the Iray panels; the Phase-0 Iray work continues in parallel. Path-tracer tasks (phase3.4_path-tracer-transport onward) keep a hard entry gate. Owner action still pending and flagged, not blocking: the operator session at Painter's Iray panels.
