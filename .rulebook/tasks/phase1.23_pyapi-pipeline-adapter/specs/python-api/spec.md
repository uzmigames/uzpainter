## ADDED Requirements

### Requirement: Pipeline Scripts Run Unchanged
The UzmiGames pipeline adapter SHALL run `painter_create.py`, `painter_layer_stack.py sync` and `painter_export.py` byte-unchanged through `UzPainter.exe run`, replacing only the transport, and MUST refuse a script whose SHA-256 differs from the pinned value.

#### Scenario: Wand v1 rebuild through the adapter
Given the wand v1 inputs and the three pipeline scripts with pinned SHA-256 values
When the adapter runs create, sync and export
Then each script completes and returns its `result` as JSON with captured stdout and stderr

### Requirement: Private Call Served Outside The Facade
The pipeline's private call `_substance_painter.display.save_viewport` SHALL be served only by an adapter shim, visible only to adapter-run scripts and listed as a migration, and the facade MUST NOT expose it.

#### Scenario: Plain script looks for the private module
Given a script run with `UzPainter.exe run` outside the adapter
When it imports `_substance_painter`
Then the import fails

### Requirement: Missing Capability Fails Explicitly
While `painter_viewport` capture or smart presets are unavailable, the script paths that need them MUST fail with an explicit capability error before mutation and SHALL NOT report success.

#### Scenario: Capture requested in Phase 1
Given the adapter running `painter_layer_stack.py capture` before the viewport capture exists
When the shim is called
Then the script fails with a capability error naming `painter_viewport` and the revision is unchanged

### Requirement: Sync Keeps Unrelated Content
Running `painter_layer_stack.py sync` through the adapter SHALL rebuild only the addressed group and MUST hide, not delete, the other root groups unless the keep-visible prefixes match them, leaving unrelated roots and resources intact.

#### Scenario: Sync one group
Given a project with root groups `metal`, `wood` and `extra`, and a resource used only by `extra`
When `sync` rebuilds `wood` without keep-visible prefixes
Then `wood` is rebuilt, `metal` and `extra` are hidden but present, and the resource remains in the project
