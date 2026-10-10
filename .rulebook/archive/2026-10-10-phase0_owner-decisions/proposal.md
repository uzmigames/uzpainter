# Proposal: phase0_owner-decisions

## Why
Phase 0 opens by recording the owner's answers of 2026-10-10 so that implementation proceeds on decided ground and no decided point is asked again (`docs/roadmap.md` Phase 0; `docs/dag.md` node P0-OWNER, implements all of D1–D14). The answers bind requirements across the PRD: OWN-01…08, ACC-01, G-01, G-03, G-04, NFR-01, NFR-04, ARC-06…ARC-10, ARC-14, CLR-01, CLR-05 and release criterion 8 (`docs/prd.md` §2, §3, §14, §15, §18). Without accepted decision records, every later package (approved-source index, parity contract, vendoring) would have to re-derive or re-ask the owner's position.

## What Changes
Governance record only, no code. Rulebook decisions under `.rulebook/decisions/` for the owner's answers listed in `docs/open-questions.md` (Q1, Q2, Q5–Q14, repository history):

| Question | Decision | Supersedes |
|---|---|---|
| Q1 equality contract | 017 | — (refines 001) |
| Q2 render reference (Iray) | 018 | 008 |
| Q5 scope, brush strokes out of scope | 019 | 004 |
| Q6 migration through the documented API | 020 | — |
| Q8 zero UzEngine dependency, vendored render core | 021 | 014 |
| Q9 platform and CI (owner's machine as GPU runner) | 022 | — |
| Q10 export consumers | 023 | — |
| Q11 project-file policy | 024 | — |
| Q12 Python trust | 025 | — |
| Q13 Assets3D cutover trigger | 026 | — |
| Repository history before publication | 027 | — |

Q3 and Q4 stay on decision 002; Q7 and Q14 stay on decision 016 (both already accepted). The decisions were written on 2026-10-10; this task verifies them against `docs/open-questions.md` and closes the node.

## Dependencies
- Prerequisites: none (DAG Inputs: —).
- Successors that wait on this task: `phase0_approved-source-index` (P0-SOURCES), `phase0_parity-contract` (P0-CONTRACT), `phase0_vendor-render-core` (P0-VENDOR).
- Gate: reaches `phase0_gate-g0` through its successors.

## Acceptance
Decisions are recorded without re-asking decided points; work consistent with a recorded decision proceeds; only an operation that would change a decision waits for the owner (`docs/dag.md`, P0-OWNER acceptance gate).

## Impact
- Affected specs: none (governance record)
- Affected code: none
- Breaking change: NO
- User benefit: every Phase 0–5 task cites an accepted decision instead of an open question; the owner is asked again only when an operation would change a recorded decision (`rulebook_task {action:"ask"}`)
