## ADDED Requirements

### Requirement: Every Required Operation Has A Typed Tool
The requirement-to-typed-operation matrix generated from the frozen release build SHALL map every required operation to a typed MCP tool and a conformance fixture; a required operation without a typed tool MUST be reported as a release gap and MUST fail conformance.

#### Scenario: Matrix row without a tool
Given a test build in which one required operation has no typed tool
When the matrix is generated and the suite runs
Then that row is reported as a release gap and the conformance result fails

### Requirement: Python Disabled By Default At Release
With the supervisor started without `--allow-python`, `run_python` MUST be absent from the tool list and MUST be rejected at the IPC boundary with `python_disabled`; no required operation SHALL depend on it.

#### Scenario: Client asks for run_python
Given the frozen build started as `UzPainter.exe --mcp` without `--allow-python`
When the client lists tools and then sends a `run_python` request through the pipe
Then the tool is not listed and the request returns `python_disabled`

### Requirement: Conformance Fixture Per Operation Family
Each required operation family (project lifecycle, texture sets, resources, the stack family with the Phase 4 kinds and paint layers receiving bitmaps and projections, recipes, native bake, mesh reload, every export target, capture in each mode, diagnostics, jobs and lease) SHALL have a conformance fixture that passes with Python disabled on the frozen build.

#### Scenario: Recipe family with Python disabled
Given a project and a stack JSON addressing layers by name
When the fixture calls `sync_stack` with a group-only rebuild through MCP with Python disabled
Then only the named group is rebuilt, the result reports the changed ids and the committed revision, and the fixture passes

#### Scenario: Capture family in the parity mode
Given the frozen build on the self-hosted GPU runner
When the fixture calls `capture` with mode `painter_iray`
Then the call returns a receipt with the revision and a downscaled image block, and no Python executes

### Requirement: Mutation Contract Holds In Every Fixture
Every mutating tool exercised by the suite MUST accept `idempotency_key` and `expected_revision` and MUST return `revision`, `committed_revision`, `job_id` where applicable, the change lists and `warnings`, or a structured error on failure.

#### Scenario: Retry of a conformance mutation
Given a mutating fixture call that committed revision R
When the same call is retried with the same `idempotency_key` and arguments
Then the recorded outcome with `committed_revision` R is returned and no second revision is created

### Requirement: Conformance Recorded On The Frozen Build
The conformance result SHALL be written to `parity/reports/phase5/mcp-conformance.json` with one row per matrix row and MUST name the build hash shared with the packaged distribution and the tier report.

#### Scenario: Result file produced
Given the suite finished on build hash H
When the result is written
Then every matrix row appears with its tool, fixture and outcome, and the file records build hash H
