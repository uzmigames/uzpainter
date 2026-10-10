# 24. Q11 Project file policy: self-contained portable .uzp, 10 % candidate budget, checkpoint and revision retention

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

Owner question Q11 asked for the size ratio after the census, the checkpoint and history policy, and self-contained versus linked resources. D8 (decision 010) defines the SQLite container with a canonical JSON manifest. Owner answer of 2026-10-10 (docs/open-questions.md Q11).

## Decision

A .uzp project is a self-contained portable file by default: every dependency is embedded, and linked resources are an explicit non-portable opt-in. The candidate size budget is 10 % of the matched .spp; the Phase 1 census measures matched content (project plus external dependency bytes on both sides) and the budget is ratified from it. Retention keeps the current and previous checkpoints plus the last 50 mutation revisions, besides named and protected checkpoints; older mutation revisions are collapsed by compact. See docs/architecture/09-project-file-format.md.

## Alternatives Considered

- Linked resources by default - rejected: portability first; linking is an explicit opt-in
- Unbounded mutation history - rejected: bounded at the last 50 revisions

## Consequences

The census report is a release item; 10 % is a candidate, not a gate, until the census is ratified. Recovery can always return to the current or previous checkpoint or any of the last 50 mutation revisions.
