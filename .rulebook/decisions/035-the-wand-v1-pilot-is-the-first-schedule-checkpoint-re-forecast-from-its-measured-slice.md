# 35. The Wand v1 pilot is the first schedule checkpoint; re-forecast from its measured slice

**Status**: accepted
**Date**: 2026-10-11

## Context

The 30-39 week roadmap is a hypothesis with no multi-week velocity data (all work so far in about two days, 3% of checklist items). Three of four reviewing models warned that checklist throughput measures scaffolding, not integration, and asked for an end-to-end vertical slice before trusting forecasts. Decided by the model panel under the owner's delegation of 2026-10-11 (2 ACCEPT, 1 ACCEPT-WITH-CHANGE, 1 ACCEPT with note; merged). Analysis: docs/analysis/multi-model-review/.

## Decision

Scope and order stay as planned. The Phase-1 pilot P1-WAND (Wand v1: instructions -> project -> evaluation -> PNG16 export -> comparison against Painter goldens) is the first schedule checkpoint, with its existing pass criteria (maps equal to the private goldens, byte-stable across two runs). When the pilot completes, pass or fail, the roadmap records a re-forecast of every remaining phase from the slice's measured wall-clock, failure causes and exception counts, labelling which estimates are measured from the slice and which remain extrapolated (bakers, procedurals and the path tracer are not validated by a compositor slice).

## Alternatives Considered

- Keep the hypothesised durations until G5 (rejected: no evidence behind them)
- Reorder Phase 1 around an earlier thinner slice now (rejected: Wand v1 is already the thinnest end-to-end fixture the gates define; reordering costs more than it measures)

## Consequences

docs/roadmap.md gains the checkpoint rule; phase1.25_pilot-wand gains a re-forecast item. No task is added or removed now.
