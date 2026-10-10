# 16. D14 Roadmap: evidence-gated phases with Wand v1, Belt v5 then Tunic v10 as the pilot sequence

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Both architects crossed on pilot order in round 2; the simpler order isolates first failures while tunic recovery proves the owner-relevant property (05-resolution.md D14).

## Decision

Six phases with evidence gates G0-G5 (docs/roadmap.md, docs/dag.md): contract and feasibility; foundation and wand smoke; pilot parity (Belt v5, Tunic v10 recovery as the milestone that counts) and operation; native bake, procedurals and engine presets with locked bracers and hat v5 fixtures; coverage (hat v8, body v6b, remaining nodes, UV tiles, strokes per Q5); stress, packaging and cutover. Feasibility gates start in Phase 0; milestones are named by proven scope; durations are labelled Hypotheses (owner Q14).

## Alternatives Considered

- Tunic v10 first (Astra round 1; Claude round 2) - rejected: too many simultaneous failure causes for a first slice
- Feature-first implementation - rejected
- Calling the fills milestone v1 - rejected

## Consequences

DAG node ids become rulebook task ids; no full-replacement claim while required gaps are open.
