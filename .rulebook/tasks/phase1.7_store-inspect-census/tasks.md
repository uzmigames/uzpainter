## 1. Prerequisites
- [ ] 1.1 Prerequisites accepted: phase1.3_document-model, phase1.4_store-container-operations, phase1.5_store-planes, phase1.6_store-save-retention

## 2. Implementation
- [ ] 2.1 Implement `inspect` with every field of `docs/architecture/09-project-file-format.md` §6 (recipe digest reported as unavailable until P2-RECIPE), `--revision N` and `--verify`, without GPU and without the project lock
- [ ] 2.2 Implement `export-bundle` to a directory or ZIP (`manifest.json`, `res/`, `meshmaps/`, `planes/` at native precision) and bundle import through `project.open`
- [ ] 2.3 Implement the census instrumentation counters and the report writer (numbers only)
- [ ] 2.4 Run the instrumentation on the dependency content of tunic v10, hat v8 and the body versions and write `parity/reports/phase1/store-census.json`

## 3. Tests
- [ ] 3.1 `inspect` on a fixture project prints every §6 field, lists project-file bytes and external dependency bytes separately, and runs while another process holds the project lock
- [ ] 3.2 `inspect --verify` fails on a fixture with a broken plane binding and on one with a missing blob
- [ ] 3.3 `export-bundle` round trip: bundle → `project.open` → manifest digest and plane pixels equal the source project
- [ ] 3.4 Census instrumentation reports bytes per edit, reopen time, compaction time and retained-history size for a scripted edit sequence

## 4. Acceptance
- [ ] 4.1 Tests of this child green on the hosted CPU lane; census report written; results attached to `phase1.8_project-store`

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [ ] 5.1 Update or create documentation covering the implementation
- [ ] 5.2 Write tests covering the new behavior
- [ ] 5.3 Run tests and confirm they pass
