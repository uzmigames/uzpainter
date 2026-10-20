## ADDED Requirements

### Requirement: Isolation Leaves The Document Unchanged
`isolate(layer)` SHALL evaluate the stack with one node hidden and MUST restore the prior visibility state atomically without committing a revision.

#### Scenario: Isolate a fill layer
Given a project at revision 20 with every layer visible
When `isolate` runs on one fill layer
Then the isolated output equals the export with that layer hidden, and the project is still at revision 20 with every layer visible

### Requirement: Diagnostics Come From The General Engine
Every diagnostic view MUST equal the export of the same diagnostic source through the general evaluation and export engine.

#### Scenario: Contribution map
Given a layer L in an evaluated stack
When `contribution(L)` is computed
Then it equals the decoded difference between the export with L and the export without L

### Requirement: Material Leak Views
`material_views(mask)` SHALL return per-channel values under a material mask for ID, BaseColor, Height, Normal, Roughness and Metallic so that leaks are detectable.

#### Scenario: Seeded roughness leak
Given a synthetic fixture whose Roughness bleeds outside its material mask
When `material_views` runs with that mask
Then the Roughness view shows non-zero values outside the mask

### Requirement: Layer-Tree Snapshot Diff
`diff_snapshots` MUST report exactly the added, removed and modified nodes and parameters between two layer-tree snapshots.

#### Scenario: One parameter changed
Given two snapshots differing only in one layer's opacity
When they are diffed
Then the diff lists that layer and parameter and nothing else
