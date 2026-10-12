## ADDED Requirements

### Requirement: Every Setter Reads Back
Every setter of the `uzpainter` module SHALL have a matching getter, and a value set through it MUST read back equal through a freshly resolved handle before and after save and reopen.

#### Scenario: Fill value survives reopen
Given a fill layer whose roughness uniform value is set to 0.35 through `uzpainter.source`
When the project is saved, reopened and the layer is resolved again by `layerstack.get_node_by_uid`
Then the getter returns 0.35

### Requirement: Handles Reject Unknown Attributes And Stale Use
Handles MUST use `__slots__` so that assigning an unknown attribute raises `AttributeError`, and a handle to a deleted node MUST raise `ValueError` on use.

#### Scenario: Misspelled attribute
Given a paint layer handle
When a script assigns `handle.active_channels_typo = {...}`
Then `AttributeError` is raised and the document revision is unchanged

### Requirement: One Call Is One Transaction
Each API call SHALL commit as one transaction whose result enumerates created, modified and hidden node ids and imported or skipped resources; a failed call MUST leave its mutation unapplied, and only the native `Transaction` context manager SHALL make several calls atomic.

#### Scenario: Script raises after two calls
Given a script that adds two fill layers and then raises
When the script runs
Then both layers remain committed and the error receipt names the last committed revision

#### Scenario: Transaction block raises
Given a `with uzpainter.Transaction():` block that adds two layers and then raises
When the block exits with the exception
Then no revision is committed and neither layer exists

### Requirement: No Silent No-Op
A call whose behaviour is not yet implemented MUST raise `NotYetSupported` before any mutation, and no failing call SHALL return an empty success.

#### Scenario: Bake requested in Phase 1
Given an open project
When a script calls a `uzpainter.baking` operation
Then `NotYetSupported` is raised and the revision is unchanged

### Requirement: Native Values Never Reset On Toggle
The native API SHALL keep every channel value when active channels are changed (LAY-01).

#### Scenario: Toggle active channels after setting sources
Given a fill layer with base colour and roughness sources set
When `active_channels` is reassigned through `uzpainter.layerstack`
Then the previously set source values read back unchanged

### Requirement: Stack Sync Rebuilds Only The Named Group
`layerstack.sync_stack` SHALL load the stack JSON without editing it, rebuild only the named root group and hide, never delete, the other root groups unless their names match the keep-visible prefixes, and MUST leave unrelated roots and resources intact.

#### Scenario: Sync one group of three
Given a stack with root groups A, B and C and resources used only by C
When `sync_stack` rebuilds group B with keep-visible prefix `A`
Then B is rebuilt, A stays visible, C is hidden but present, and C's resources remain in the project

### Requirement: Ambiguous Names Fail Before Mutation
A name-addressed operation MUST fail before mutation when the name matches more than one node in its explicit project, set, stack and parent scope, and repeating the same named operation SHALL NOT create a duplicate node.

#### Scenario: Two layers share a name
Given two layers named `trim` under the same parent
When a script sets the opacity of the layer named `trim`
Then the call fails listing both candidate ids and the revision is unchanged

### Requirement: GIL Released Around Waits
The Python command thread SHALL release the GIL around every engine-thread and job wait and MUST NOT hold the document lock while waiting.

#### Scenario: Export wait
Given a script waiting on `uzpainter.export` for a running export job
When a second Python thread executes during the wait
Then that thread makes progress and the export completes normally
