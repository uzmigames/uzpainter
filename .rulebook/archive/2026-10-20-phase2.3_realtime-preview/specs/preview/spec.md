## ADDED Requirements

### Requirement: Preview Settling Evidence
The preview subsystem SHALL demonstrate on the wand v1 project that captures run without any window and that the preview window never pauses evaluation, and MUST report `painter_iray` as an explicit unavailable capability.

#### Scenario: Export with the preview attached
Given a worker with the preview window attached and stalled by a test hook
When the wand v1 export runs
Then the exported bytes equal those of a run without preview and the engine thread never waits on the preview thread

#### Scenario: Capabilities in Phase 2
Given the Phase 2 build
When a client reads the capability manifest
Then `painter_iray` is listed as unavailable and `painter_viewport` is not described as a parity target
