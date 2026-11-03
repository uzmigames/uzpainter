# 397. Gate tasks run last, after every feature task of their phase passed its own tests

**Status**: accepted
**Date**: 2026-11-03
**Related Tasks**: phase1.26_gate-g1, phase2.11_gate-g2

## Context

The owner, on 2026-11-03, verbatim: "pra mim so faz sentido esses testes completos quando a aplicacao ja foi testado em cada feature separado, ve c te outras tasks assim e joga pra frente" (in English: complete test runs only make sense once the application has been tested feature by feature; find other tasks like that and push them later).

The phase gates `phase1.26_gate-g1` and `phase2.11_gate-g2` are such tasks: their records rest on whole-phase runs (guard, store verify, capability manifest, the coordinated suite on the gate commit).

## Decision

1. `phase1.26_gate-g1` and `phase2.11_gate-g2` run last in their phase: their gate runs start only after every feature task of that phase has passed its own affected tests (CLAUDE.md, test-time override of 2026-10-12).
2. Unchanged: the gates' checklists and clauses, the task ids and their dependency levels, and the coordinator's full suite per merge batch.

## Consequences

- Each gate task's `tasks.md` carries one note naming this decision.
- Feature tasks are worked first; the gates wait for them.
