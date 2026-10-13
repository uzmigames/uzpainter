# Proposal: phase1_docs-status-refresh

## Why
The owner asked (2026-10-13) to update everything that is out of date in the documentation, README included. A status check found the README "Project Status" table still says Gate G0 is Planned and the Iray capture procedure is In progress, while phase0.10_gate-g0 and phase0.9_render-reference-capture were archived on 2026-10-13. Other docs may still describe hosted CI (removed, decision 200), features as planned that now exist (preview window, capture modes, export PNG encode), or superseded decisions.

## What Changes
Documentation only. Every status or fact statement in the living docs is checked against the source of truth (code, `.rulebook/tasks` vs `.rulebook/archive`, the latest `.rulebook/decisions`, `git log`) and corrected where it is wrong. Historical records are not rewritten: `.rulebook/decisions/`, `.rulebook/archive/`, `docs/analysis/` and dated reports under `parity/reports/` stay as written.

Scope, split into four disjoint file sets:
1. Root and project docs: `README.md`, `docs/*.md` (README, roadmap, task-index, dag, open-questions, prd, vision, approved-sources, licensing-and-clean-room).
2. Architecture: `docs/architecture/**`.
3. Parity: `parity/*.md` and any index/README under `parity/reports/`.
4. Module docs: `src/*/README.md`, `python/FACADE.md`, `adapters/**/*.md`, `tools/**/*.md`.

## Impact
- Affected specs: none
- Affected code: none (documentation only)
- Breaking change: NO
- User benefit: the docs say where the project really is and what can be run today
