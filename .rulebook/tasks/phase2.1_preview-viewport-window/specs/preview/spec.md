## ADDED Requirements

### Requirement: Viewport Is A Preview, Not A Parity Target
The `painter_viewport` pass SHALL render the project with realtime approximations of the shared material model and display transform, and its outputs MUST NOT be used as parity or acceptance evidence.

#### Scenario: Viewport regression check
Given a fixed build, adapter and driver
When the viewport renders the bevelled-cube fixture
Then the output equals the stored UzPainter viewport regression golden byte for byte and is reported as a repeatability check, not a tier result

### Requirement: Preview Window Never Pauses Evaluation
The preview window SHALL be read-only with an orbit camera only, and its thread MUST NOT block or pause the engine thread.

#### Scenario: Preview thread stalled
Given a preview window attached to a worker
When the preview thread is stalled by a test hook during an export
Then the export completes with the same bytes as without a preview

### Requirement: Unsupported Display Configuration Fails Explicitly
The only supported display configuration SHALL be OCIO with Painter's substance config and the view `Default - sRGB` (decision 038). Any other configuration, including Legacy `Linear` and `ACES`, MUST fail with an explicit error before rendering.

#### Scenario: ACE-mode project
Given a project created in ACE colour-management mode
When the viewport is asked to render it
Then rendering fails with an explicit unsupported-configuration error

#### Scenario: Legacy project
Given a project created without OCIO colour management (Legacy mode)
When the viewport is asked to render it
Then rendering fails with an explicit unsupported-configuration error naming decision 038 and nothing is drawn
