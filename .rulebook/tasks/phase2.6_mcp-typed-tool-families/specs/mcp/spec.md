## ADDED Requirements

### Requirement: Typed Tools For Every Available Operation Family
The MCP server SHALL expose the typed tool groups of `docs/architecture/11-mcp-server.md` §2, each forwarding to a native operation, so that every operation available in the build is reachable without `run_python`.

#### Scenario: Stack edit with Python disabled
Given a supervisor started without `--allow-python` and an open project
When a client inserts a fill layer with `layer_insert` and sets its blending with `layer_set`
Then both calls commit and their receipts carry `revision`, `committed_revision` and the created and modified ids

### Requirement: Unavailable Families Report A Capability Gap
A tool whose native implementation is not in the build MUST fail with a structured capability-gap error before any mutation and MUST appear as a gap in `uzpainter://capabilities`.

#### Scenario: Native bake before the bakers exist
Given a Phase 2 build without native bakers
When a client calls `bake_start`
Then the call fails with the capability-gap error, no revision is committed and the capabilities resource lists native bake as a gap

### Requirement: Stack Sync Rebuilds Only The Named Group
`sync_stack` SHALL rebuild only the named root group, MUST hide rather than delete the other root groups unless `keep_visible` matches them, and MUST leave unrelated resources intact.

#### Scenario: Sync one group of three
Given a stack with root groups A, B and C and imported resources
When `sync_stack` rebuilds group B
Then B is rebuilt, A and C still exist hidden, and every resource still resolves

### Requirement: Batch Stops On Error With Per-Call Results
`batch` with `stop_on_error` MUST stop at the first failing call and SHALL return a result for each executed call.

#### Scenario: Second call fails
Given a batch of three calls where the second is invalid
When the batch runs with `stop_on_error: true`
Then the first call's result is reported, the second reports its error and the third is not executed
