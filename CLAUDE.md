<!-- RULEBOOK:START v7.0.0 — generated; put custom content outside this block. -->

# CLAUDE.md

Managed by @hivehub/rulebook — few rules, all deliberate.

## Project overrides (user-owned, survive updates, win on conflict)
<!-- @AGENTS.override.md (skipped — target file not present) -->

## Commands
- Before each commit: type-check + lint + tests covering the change.
- Before push/PR/task archive: FULL quality gate (type-check → lint → full
  suite), all green. Never bypass hooks — pre-commit/pre-push wiring is the floor.
- Type-check before tests; it is the faster signal.
- No OS schedules (cron, systemd, launchd, schtasks): scheduling lives in the app.

## Values
1. Complete implementations — no stubs or TODO markers; finish, or say concretely why you can't.
2. Root causes, not workarounds — diagnose before changing code; never guess at bug causes.
3. Surgical diffs — touch only what the task needs; match existing style.
4. Simplicity first — the least code that solves the problem; nothing unrequested.
5. Fix forward — never discard uncommitted work.
6. State assumptions — if interpretations diverge, say so instead of picking silently.

## Communication
- Plain words over jargon; gloss a term when it isn't obvious from context.
- Answer first, reasoning after.
- Cut what the reader knows and options you didn't take. Length follows
  the result, not the effort behind it.

## Git safety (requires explicit user authorization)
`reset --hard` · `checkout -- .` / `restore .` · `clean -f` · `push --force` ·
`rebase` on shared branches · `stash` · `branch -D` · switching a shared checkout
with changes you did not author. Yours: status/diff/log/add/commit,
branches you create (create/switch/merge), `git worktree`, PRs via `gh`.
Worktrees live outside the repo tree and come out via `git worktree remove` —
never `rm -rf` a worktree, never delete or move a `.git`.

## Orchestration
Gate first: act on Jev `routing` from the prompt hook, else from
`rulebook_gate {prompt}`; unavailable or undecided → these rules. Main session never does the work itself — delegate each task to one subagent, model set
per call: Fable 5.1 architecture, hard bugs, review; Opus 5.5 edits, tests, docs,
refactors (never Fable for simple work); Haiku 4.5 research, summaries. Plan first;
parallelize independent agents; read reports, not files. Subagents archive their task.
Monitor; pause/restart stalled agents; review, then update CHANGELOG.
See `.rulebook/specs/orchestration.md`.

## Rulebook (on demand — no ceremony for small fixes)
- Multi-session or multi-phase work: track via the `rulebook` MCP (`rulebook_task`).
  Checklist order = dependencies; independent items may run in parallel.
- Undecidable choice? `rulebook_task {action:"ask"}`, show the form. Same request
  again? Capture a learning under one title; at 2+ promote it to a skill.
- Optional: `rulebook_session` (context), `rulebook_memory` (learnings).
- Read a `.rulebook/specs/` spec when work touches its area.
- Analyses: `docs/analysis/<slug>/`, numbered files, one theme each.
- `/compact <focus>` at a task boundary (~60% context); after an archive
  `/clear` is free — state lives in `.rulebook/`.

<!-- RULEBOOK:END -->

## Test time budget (owner override, 2026-10-12 — wins over "Commands" above)
Tests had eaten most of the wall clock: agents spent 60–80% of their time waiting
on runs, and four GPU suites ran at once and slowed each other down.
- **Agents run only the tests their change touches**: the changed test files, narrowed
  with `-k` or node ids to the cases that change touches, plus ruff/mypy on touched
  files. They never run the whole `tests/evaluator`, `union_run.py` or bare `pytest`.
- **If the change does not touch GPU or native code, do not run GPU tests.** Docs,
  manifests, recorder, export Python and rulebook changes never run `tests/evaluator`.
- **Only one GPU run at a time on the machine** (`tests/evaluator`, `union_run`,
  native cases). Before starting one, check for a running
  `pytest tests/evaluator` or `union_run` process. If one is running, do other work
  (lint, type-check, docs) and start yours after it ends.
- **Run each test command once.** Never re-run a set that already passed. After a fix,
  re-run only the tests that failed, by node id.
- **Run long commands with `run_in_background` and wait for the completion notice.**
  Never poll with `sleep` or `until grep` loops.
- **The full suite is the coordinator's job, once per merge batch**, in a worktree,
  with no other GPU run going. Task archive and merge need only the affected tests,
  not the full gate. The full gate runs once before the owner pushes.
- **A branch whose affected tests passed is merged without being re-verified.**
- **Subagents do not spawn subagents that run tests.**
- **A single test command expected to take more than 10 minutes** belongs to the
  coordinator's batch, not to an agent.
