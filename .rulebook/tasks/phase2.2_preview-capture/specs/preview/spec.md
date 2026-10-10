## ADDED Requirements

### Requirement: Captures Are Window-Independent
Every capture SHALL render to an offscreen target without a window, swapchain or desktop focus.

#### Scenario: Headless runner
Given the self-hosted GPU runner with no interactive desktop session
When a `painter_viewport` capture of an open project is requested
Then the PNG and its receipt are written without creating any window

### Requirement: Captures Reflect The Latest Revision
A capture MUST wait for evaluation of the current revision and all resource uploads and MUST record that revision in its receipt together with mode, backend, adapter, driver, samples, seed, camera, size, display configuration and hashes.

#### Scenario: Capture after a mutation
Given a project at revision 7
When a layer is changed (revision 8) and a capture is requested immediately
Then the receipt names revision 8 and the image shows the change

### Requirement: Diagnostic Captures Are Exact
Diagnostic captures (unlit BaseColor, single channel, mask/ID) MUST equal the corresponding channel exports in decoded values.

#### Scenario: Roughness channel capture
Given an evaluated texture set
When `capture(mode="channel:roughness")` runs at the set resolution
Then its decoded values equal the roughness channel export

### Requirement: Iray Mode Unavailable Until The Path Tracer Passes
Until the path tracer passes, `painter_iray` MUST fail with an explicit unavailable-capability error before any work and MUST be listed as a release gap.

#### Scenario: Iray capture requested in Phase 2
Given a Phase 2 build
When a client requests `capture(mode="painter_iray")`
Then the call fails with `PathTracerUnavailable` and nothing is rendered
