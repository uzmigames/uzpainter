# 27. Release criterion: recreate clean repository history before the repository is made public

**Status**: accepted
**Date**: 2026-10-10
**Related Tasks**: phase2_docs-architecture

## Context

The private repository uzmigames/uzpainter has initial commit 6d7c297, which contains analysis text written before the clean-room sanitisation recorded in docs/analysis/clean-room-redactions.md. Decision 002 forbids publishing descriptions of Adobe implementation internals. Owner instruction of 2026-10-10.

## Decision

The repository stays private while its history contains pre-sanitisation text. Before it is made public, its history is recreated clean, with a force push at that moment. This is a release criterion (docs/prd.md release criteria, docs/licensing-and-clean-room.md, gate G5); no history rewrite happens before that point.

## Alternatives Considered

- Publish with the existing history - rejected: it would expose the redacted pre-sanitisation text

## Consequences

G5 cannot authorise a public release until the clean history exists. The force push is a destructive git operation and is performed only at publication time.
