# Changelog

All notable changes to UzPainter are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

No source code exists yet. The entries below record the documentation foundation
that engineers and AI agents build UzPainter from; start with the reading order in
`docs/README.md`. The build contract is `docs/`; the files under `docs/analysis/`
are historical evidence and are not implementation inputs until the approved-source
index (work package `P0-SOURCES` in `docs/dag.md`) clears their exact revision.

## [Unreleased] - 2026-10-10

### Added

- Approved-source index (task `phase0.1_approved-source-index`): `docs/approved-sources.md` lists the public specifications, public Adobe documentation, UzmiGames files and the 21 cleared `docs/analysis/` files (pinned by blob hash), plus the quarantine list (25 files and every uncleared revision); architecture citations aligned; citation and revision checks in `tools/sources/` with tests in `tests/sources/`.
- Vendored UzEngine render core (task `phase0.1_vendor-core-copy`): 97 files copied byte-equal from UzEngine commit `380c142e` into `thirdparty/uzengine-render-core/` with `LICENSE`, `ORIGIN.md` and `MANIFEST.json`; root `NOTICE`; `.gitattributes` keeps the vendored folder free of line-ending conversion; Python tooling base (`pyproject.toml`: ruff, mypy strict, pytest) with vendoring checks in `tools/vendoring/` and tests in `tests/vendoring/`.
- Apache-2.0 licence for the project: `LICENSE`.
- Product documents: `docs/vision.md` (product definition, acceptance premise), `docs/prd.md` (numbered requirements with acceptance criteria), `docs/roadmap.md` (evidence-gated phases G0–G5), `docs/dag.md` (work-package graph with stable rulebook task ids), `docs/open-questions.md` (owner questions Q1–Q14, all answered 2026-10-10), `docs/licensing-and-clean-room.md` (clean-room rules, third-party licence inventory); index and reading order in `docs/README.md`.
- Fourteen architecture documents, `docs/architecture/01-overview.md` to `docs/architecture/14-parity-testing.md`: overview, runtime topology, project model, layer stack and compositing, procedural content, baking, preview and render parity, export, project file format, Python API, MCP server, mesh import, engine integration, parity testing.
- Four source-cited analyses, each with its review response: `docs/analysis/substance-parity/` (`08-review-response.md`), `docs/analysis/assets3d-pipeline/` (`09-review-response.md`), `docs/analysis/uzengine-renderer/` (`10-review-response.md`), `docs/analysis/technology-options/` (`05-review-response.md`); index in `docs/analysis/README.md`.
- Astra's independent reviews in `docs/analysis/reviews/`: one per analysis (`substance-parity-`, `assets3d-pipeline-`, `uzengine-renderer-`, `technology-options-astra-review.md`) and the final review of the docs set (`docs-set-astra-review.md`, 23 findings).
- Architecture discussion record, rounds 1–4: `docs/analysis/architecture-discussion/01-claude-proposal.md` to `06-round4-changes.md` (06 records how the owner's answers of 2026-10-10 and the docs-set review findings were applied).
- Clean-room redaction log for the sanitisation pass over `docs/analysis/` (102 redactions): `docs/analysis/clean-room-redactions.md`.
- Rulebook decisions 001–027 in `.rulebook/decisions/`: 001 output parity, 002 Apache-2.0 and clean room, 003–016 the D1–D14 outcomes, 017–027 the owner's answers of 2026-10-10. Decisions 004, 008 and 014 are superseded by 019 (D2), 018 (D6) and 021 (D12).
- Archived phase-1 research tasks in `.rulebook/archive/`: `2026-10-10-phase1_analysis-substance-parity`, `2026-10-10-phase1_analysis-assets3d-pipeline`, `2026-10-10-phase1_analysis-uzengine-renderer`, `2026-10-10-phase1_analysis-technology-options`.
- Astra's verification of the round-4 corrections, `docs/analysis/reviews/docs-set-astra-verification.md`, and its fixes: idempotency stays safe after pruning and ledger loss (02, 09, 11), revert restores the exact raster contents through immutable plane versions (09), fixed-name export consumers read one complete generation (08, PRD EXP-06/INT-11), `not_migratable` fixtures keep their gate blocked without an owner scope decision (roadmap, DAG, 14), MCP acceptance split by milestone (11, DAG), Phase 2 capture limited to preview and diagnostic modes (07, DAG).
- Archived architecture task `phase2_docs-architecture` in `.rulebook/archive/`.
