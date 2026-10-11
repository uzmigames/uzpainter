## ADDED Requirements

### Requirement: Every unconfirmed Iray setting answered
The render procedure package MUST give an evidence-backed answer for every "not confirmed" row of `07-preview-and-render-parity.md` §2.1 and for bump vs displacement, and MUST mark a setting `uncontrolled` when it cannot be fixed or read.

#### Scenario: Unreadable setting becomes uncontrolled
Given an Iray panel setting that the probe can neither fix nor read back
When the procedure is written
Then the setting is listed as `uncontrolled` in the procedure report

### Requirement: Readiness and current-frame verification
The qualified procedure MUST capture only when Status reads Done, Iterations equals S and Rendering time is below Max Time, and MUST reject a saved image that predates the last settings change or convergence or whose silhouette does not match the fixture projected from the recorded camera.

#### Scenario: Unconverged render is refused
Given an Iray render with Iterations below S
When the operator attempts a capture
Then the procedure refuses the capture

#### Scenario: Stale frame is rejected
Given a saved render whose timestamp predates the last settings change
When current-frame verification runs
Then the capture is rejected

### Requirement: Pixel route named
The qualified procedure MUST name its pixel route: Save Render at the override resolution, or the external 1:1 observation fallback recorded as display-referred 8-bit when Save Render proves unusable.

#### Scenario: Route recorded in every reference
Given a reference captured with the qualified procedure
When its manifest entry is written
Then it names the procedure version and the pixel route used
