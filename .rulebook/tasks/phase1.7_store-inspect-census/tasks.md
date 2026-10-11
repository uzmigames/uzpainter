## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.4_store-container-operations, phase1.5_store-planes, phase1.6_store-save-retention

`phase1.3`, `phase1.4` and `phase1.5` are archived. `phase1.6_store-save-retention` is complete
locally (commit `4c75222`, all local checks green) and only waits for its hosted CI run; its code
(`save.h`, `compact.h`, `lock.h`) is treated as accepted and is what this task's `inspect`,
`export-bundle` and census build on.

## 2. Implementation
- [x] 2.1 Implement `inspect` with every field of `docs/architecture/09-project-file-format.md` §6 (recipe digest reported as unavailable until P2-RECIPE), `--revision N` and `--verify`, without GPU and without the project lock
- [x] 2.2 Implement `export-bundle` to a directory or ZIP (`manifest.json`, `res/`, `meshmaps/`, `planes/` at native precision) and bundle import through `project.open`
- [x] 2.3 Implement the census instrumentation counters and the report writer (numbers only)
- [x] 2.4 Run the instrumentation on the dependency content of tunic v10, hat v8 and the body versions and write `parity/reports/phase1/store-census.json`

## 3. Tests
- [x] 3.1 `inspect` on a fixture project prints every §6 field, lists project-file bytes and external dependency bytes separately, and runs while another process holds the project lock
- [x] 3.2 `inspect --verify` fails on a fixture with a broken plane binding and on one with a missing blob
- [x] 3.3 `export-bundle` round trip: bundle → `project.open` → manifest digest and plane pixels equal the source project
- [x] 3.4 Census instrumentation reports bytes per edit, reopen time, compaction time and retained-history size for a scripted edit sequence

## 4. Acceptance
- [ ] 4.1 Tests of this child green on the hosted CPU lane; census report written; results attached to `phase1.8_project-store`

The census report is written (`parity/reports/phase1/store-census.json`) and the results are in
`parity/reports/phase1/store-inspect-census.md`. Open: the hosted CPU lane. After the owner pushes,
the hosted run must show `zig build painter uzp-store uzp-store-tests uzp-store-save-tests
uzp-store-inspect-tests` with zero warnings and `python -m pytest` green, including
`tests/store/test_store_inspect.py` (7 native cases, the ZIP bundle and the PNG-reader cases) and
`tests/parity/test_guard.py::test_store_census_report_holds_numbers_and_identifiers_only` /
`::test_repository_store_census_report_passes`, plus `python -m tools.parity.guard` reporting
0 blocked with the census report in the tree (the hosted lane has no store index, decision 028).
The census itself is a local run only: it reads the Assets3D corpus and the `.spp` file sizes,
which no hosted machine has.

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass

## Evidence (owner's machine, 2026-10-11)

| Check | Result |
|---|---|
| `zig build painter` (Debug) and `-Doptimize=ReleaseFast` | exit 0, no warnings |
| `zig build uzp-store uzp-store-tests uzp-store-save-tests uzp-store-inspect-tests` | exit 0, no warnings (`-Wall -Wextra -Werror` on own sources) |
| `python -m pytest tests/store` | all passed (14 cases of `test_store_inspect.py` among them) |
| `python -m pytest` (full suite) | see `parity/reports/phase1/store-inspect-census.md` §1 |
| `mypy`, `ruff check`, `ruff format --check` | clean (178 files) |
| `python -m tools.parity.guard` | 2313 files checked, 0 blocked (census report covered by the new `PATH_RULES` entry) |
| Census | 5 projects measured; tunic v10 at 6.2 % of its `.spp`, hat v8 53.2 %, body v5/v6/v6b 17.5 / 14.2 / 13.0 %. Store overhead is a fraction of a percent: the ratio is decided by which dependency content each side holds, and `not_measured` names the content the corpus no longer keeps as files. Full-content comparison: `phase4.1_coverage-body-v6b`. |
