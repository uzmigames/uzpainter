## ADDED Requirements

### Requirement: Budgets Measured On Equal Outputs
The measurement harness SHALL record wall time, peak VRAM and peak RAM per fixture, operation and backend on the certified corpus, and MUST measure only fixtures whose Tier 1 outputs are equal; every record MUST carry hardware, driver, backend, build hash and resource hashes.

#### Scenario: Corpus measured on both backends
Given G4 accepted and the self-hosted GPU runner with DX12 and Vulkan available
When the harness runs the corpus
Then the budget report holds one timing and memory record per fixture, operation and backend, each tagged with its build hash and backend

#### Scenario: Fixture without equal outputs
Given a fixture whose Tier 1 comparison is not equal
When the harness is asked to measure it
Then the fixture is reported as not measured with that reason and no budget is derived from it

### Requirement: Scale Workloads Measured Separately
Each NFR-03 workload SHALL be measured on its own fixture: three 4096² texture sets in one project, 30–45-layer stacks, more than twenty 4K 16-bit masks and up to seven delivered maps per set; a combined worst case MUST NOT be reported as an observed baseline.

#### Scenario: Body v6b three sets
Given the body v6b project with three 4096² texture sets
When the harness evaluates and exports all three sets
Then the sets complete in sequence within the tuned tile budget on DX12 and on Vulkan and their peak VRAM is recorded

### Requirement: Explicit Admission Against The Budget
The engine SHALL derive the tile admission budget from the VRAM budget queried at startup on the active backend and MUST refuse creation of a texture set that exceeds it with an explicit error, never failing later during evaluation.

#### Scenario: Oversize texture set
Given a device whose VRAM budget cannot hold an 8192² texture set
When a client creates a texture set at 8192
Then creation fails with an explicit budget error and no revision is committed

### Requirement: Tuning Does Not Change Outputs
Changing the admission budget MUST NOT change any exported byte: eviction and re-evaluation SHALL produce outputs identical to an unconstrained run.

#### Scenario: Forced eviction
Given hat v8 exported with the default budget
When the same project is exported with a lowered budget that forces LRU eviction
Then every exported file is byte-identical to the default-budget export

### Requirement: Tuning Precedes The Frozen Build
The tuned admission policy SHALL be fixed and the budget report published before the release build is frozen; the report MUST name the build hash that packaging and the final parity report use, and any later admission change MUST reopen both.

#### Scenario: Admission constant changed after freeze
Given a published budget report naming build hash H used by packaging and the parity report
When an admission constant is changed
Then the build hash changes and `phase5.2_packaging` and `phase5.4_parity-report` are reopened against the new build
