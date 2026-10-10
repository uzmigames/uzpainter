## ADDED Requirements

### Requirement: Asynchronous Project Lifecycle
`project.create` and `project.open` SHALL return immediately while loading runs on the engine thread, `project.is_busy()` MUST be true until loading completes, and `is_in_edition_state()` MUST become true only with `ProjectEditionEntered`.

#### Scenario: Open a project
Given a closed project file
When a script calls `substance_painter.project.open(path)`
Then the call returns before loading finishes, `is_busy()` is true, and `ProjectOpened` is followed by `ProjectEditionEntered` only when evaluation is ready

### Requirement: Events In Painter's Order On The Dispatcher Thread
Events SHALL be delivered on the Python dispatcher thread after the committed transition, in the order recorded by the Tier 0 event-order probes, and MUST still be delivered after the originating script returned.

#### Scenario: Handler outlives its script
Given a script that connects a handler to `ProjectEditionEntered`, starts an open and returns
When loading completes
Then the handler is called on the dispatcher thread with the event

#### Scenario: Save sequence
Given an open project
When a script saves it
Then `ProjectAboutToSave(path)` is delivered before `ProjectSaved`, matching the Tier 0 golden

### Requirement: No Python Under The Document Lock
The dispatcher thread MUST NOT hold the document lock while calling Python, so a handler that calls back into the API SHALL observe the committed state without deadlock.

#### Scenario: Handler reads the stack
Given a handler connected to `ProjectEditionEntered` that lists the texture sets
When the event is delivered
Then the handler returns the committed texture sets and no deadlock occurs

### Requirement: Explicit Computation State
Disabling engine computations SHALL defer evaluation requests and MUST NOT be a no-op; re-enabling SHALL report the deferred backlog through `is_busy()` and fire `EngineComputationsStatusChanged`.

#### Scenario: Export while computations are disabled
Given computations disabled through `application.disable_engine_computations()`
When an export is requested and computations are then re-enabled
Then the export does not evaluate while disabled, `is_busy()` is true after re-enable until the backlog drains, and `EngineComputationsStatusChanged` fires

### Requirement: Mesh Reload Callback
The facade's `reload_mesh(path, settings, cb)` SHALL call `cb(ReloadMeshStatus)` on the dispatcher thread when the reload finishes, and MUST NOT signal it through an event.

#### Scenario: Reload a changed mesh
Given an open project and a modified low-poly mesh at the same path
When a script calls `reload_mesh` with a callback
Then the callback receives a `ReloadMeshStatus` on the dispatcher thread after the reload is committed
