## ADDED Requirements

### Requirement: Inspection without opening
`uzpainter inspect` SHALL print the fields of `docs/architecture/09-project-file-format.md` §6 without a GPU and without taking the project lock, and `--verify` MUST check every integrity rule of §1.

#### Scenario: Locked project
Given a project held open by a worker
When `uzpainter inspect` runs on its file
Then the report is printed without waiting for or taking the lock

### Requirement: Importable export bundle
`uzpainter export-bundle` SHALL write the manifest, resources, mesh maps and planes as files, and `project.open` MUST accept the bundle directory with an equal manifest digest and equal plane pixels.

#### Scenario: Bundle round trip
Given a project with two paint planes
When it is exported as a bundle and the bundle is opened
Then the manifest digest and every plane's pixels equal the source

### Requirement: Census instrumentation
The store SHALL measure bytes written per edit, reopen time, compaction time, retained-history size and project versus external dependency bytes, and MUST publish the Phase 1 census as numbers only.

#### Scenario: Census run
Given the dependency content of tunic v10, hat v8 and the body versions
When the instrumentation run executes
Then `parity/reports/phase1/store-census.json` lists the measurements per project
