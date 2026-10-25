---
name: uzpainter-continuous-coordination
description: Coordinate ongoing UzPainter implementation through Rulebook dependencies when the owner explicitly requests continuous work across tasks. Use for sustained implementation and supervision, not a bounded review or one-off question.
---
# Continuous UzPainter Coordination

Source: Rulebook learning
`2026-10-23T03-08-56-continue-implementation-means-complete-open-rulebook-tasks-sequentially`,
repeated owner corrections on 2026-10-23 and 2026-10-24/25.

## Resume And Assign

Read `AGENTS.override.md`, current Rulebook tasks, `docs/task-index.md` and the
current fields of `tmp/claude-supervision*.json`. Treat old completed batches and
expired locks as historical evidence; establish current owners before editing.
Start with open dependencies and existing work, preserving task acceptance rules.

Assign disjoint files and concrete deliverables. Keep one native build owner;
native edits wait during builds. Serialize staging and commits in the shared
checkout. Follow current owner rules for worktrees, scratch files and tests.

When the owner requests the existing Claude session, discover its peer using
`claude agents --json --cwd E:\UzmiGames\UzPainter` and send briefs through
`python -m tools.claude_peer --to PEER --timeout 120` on stdin. Verify actual
delivery and subsequent acknowledgement/activity; relay exit is not completion.
Do not replace that session with an unrelated reviewer.

For requested router models, send only permitted code/public contracts through
`python -m tools.model_panel --model MODEL --deadline 180` on stdin. Read actual
returned model, completion status and finish reason. A timeout is not a review;
do useful local work instead of retry loops. Never send private Painter data.

## Keep Work Moving

Inspect each delivery, reconcile findings, and assign its next ready dependency.
Run only affected checks in project order. Reuse valid completed checks; rerun
only failures or cases affected by subsequent changes. Keep meaningful progress
updates while commands or agents run. Update supervision and Rulebook state so
another session can resume without reconstructing ownership.

A commit, helper exit or completed slice is a checkpoint. Continue through task
acceptance and legitimate archive, then the next open dependency. If one branch
is blocked, continue useful authorized work elsewhere. Ask only for missing
decisions that truly require the owner; continuity grants no new authority.

## Acceptance

Completion requires actual acceptance evidence, not the absence of current tool
calls. Synthetic tests cannot promote Painter parity; resource identity
differences and unresolved gates remain explicit. Do not archive incomplete
tasks, waive checks or manufacture metadata to keep progressing. End continuous
work only on owner stop, actual overall acceptance, or a concrete impasse with no
useful authorized work remaining. Report that impasse accurately.
