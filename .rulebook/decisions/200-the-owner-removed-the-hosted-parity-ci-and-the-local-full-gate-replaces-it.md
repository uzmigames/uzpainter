# 200. The owner removed the hosted Parity CI and the local full gate replaces it

**Status**: accepted
**Date**: 2026-10-13
**Related Tasks**: phase1.6_store-save-retention, phase1.7_store-inspect-census, phase1.8_project-store, phase2.1_supervisor-ipc-worker, phase2.2_supervisor-admission-ledger, phase2.3_supervisor-jobs, phase2.4_supervisor-worker, phase2.5_mcp-transport-registry, phase2.6_mcp-typed-tool-families, phase2.7_mcp-operation-matrix, phase2.8_mcp-server

## Context

The owner's order (2026-10-13): remove the Parity CI because it always fails. The workflow `.github/workflows/parity.yml` had one job, the hosted CPU lane of decision 028: a GitHub-hosted `windows-latest` runner with `UZP_NO_GPU=1` and no store. On every push and pull request to `main` it ran the repository guard, the vendoring check, `UzPainter.exe selftest`, mypy, ruff, the full pytest suite, and the `oracle_unavailable` check of `parity/schema/samples/public`. Several open task items waited on a green run of it after the owner's push. This is the owner's decision, so no model panel was asked.

## Decision

1. `.github/workflows/parity.yml` is deleted. `.github/workflows/codespell.yml` stays.
2. The checks stay available as local commands (`README.md`): `python -m tools.parity.guard`, `python -m tools.vendoring.vendor_check`, `zig build painter` with `UzPainter.exe selftest`, `python -m mypy`, `python -m ruff check .`, `python -m pytest`, and `python -m tools.parity.store verify parity/schema/samples/public`, which exits 1 with `oracle_unavailable` on a machine without the store.
3. The coordinator's full gate on the owner's machine, before the owner pushes, replaces the hosted run. The CPU lane of `docs/architecture/14-parity-testing.md` §7 now runs locally.
4. Decision 028 otherwise stands. There is no GPU CI and no self-hosted runner. GPU and Painter-oracle checks run on the owner's machine, and the local run report is the evidence.
5. Tests that read the workflow file are removed: the guard, store, selftest and vendoring CI-shape tests. The behaviour they protected is still tested as commands: the guard fails a commit with a blocked file when no store is present, and `store verify` reports `oracle_unavailable` without a store.
6. Open task items that waited on the hosted CPU lane now take local CPU-lane evidence from the owner's machine, in the style of decision 028. An item is checked only if the hosted lane was its only open condition and its notes already hold the local evidence:
   - phase1.6 4.1: `tests/store` 35 passed, and 56 passed on `a39594a`.
   - phase1.7 4.1: `tests/store` all passed and the guard reported 0 blocked.
   - phase1.8 2.3, 2.4 and 4.1: the five settle cases are green and `tests/store` 56 passed on `a39594a`.
   - phase2.2 4.1 and phase2.3 4.1: the merged-tree `tests/supervisor` run gave 81 passed.
   This lifts the policy hold in item 5 of decision 045. Items with other open conditions keep them: phase2.1 4.1 waits on Vulkan (decision 121), phase2.4 4.1 on Vulkan and G1, and the phase2.x prerequisite items on G1. The later items worded "hosted CPU lane" or "hosted CI" now name the local CPU lane.

## Alternatives Considered

- **Fix the hosted run instead.** Not taken. The owner ordered its removal.
- **Keep a reduced hosted job (guard and lint only).** Not taken for the same reason. The guard also runs as the pre-commit hook.

## Consequences

Nothing runs on GitHub on push except codespell. Before each push, the coordinator runs the full gate once per merge batch: type-check, lint, the full suite, the guard, the vendoring check and the selftest. Historical reports that cite hosted runs, such as Parity run `38088050428` in `parity/reports/phase1/document-model.md`, stay as recorded evidence. Wording in test docstrings and skip reasons that still says "hosted CI" means a machine without a GPU or a store. Its behaviour is unchanged.
