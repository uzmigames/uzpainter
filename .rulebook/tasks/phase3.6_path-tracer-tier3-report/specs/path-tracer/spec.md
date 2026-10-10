# Path tracer — Tier 3 report

## ADDED Requirements

### Requirement: Tier 3 Report With Noise Floor
The Tier 3 report SHALL compare `painter_iray` renders with converged Iray references in the reference's own encoding, per fixture and per material region, and MUST report max/mean/p99 |Δ|, differing-pixel count, mean signed Δ with its standard error and the downsampled statistics next to the measured noise floor; FLIP MUST be marked diagnostic only.

#### Scenario: Analytic sphere comparison
Given the analytic sphere references (two sessions plus k·S) and UzPainter renders at S with several seeds
When the Tier 3 comparison runs on the owner's machine
Then the report MUST list the noise floor, the per-region statistics and FLIP marked diagnostic, with numbers only

### Requirement: Production References Captured By The Qualified Procedure
Production-project Iray references of Wand v1, Belt v5 and Tunic v10 MUST be captured through the qualified procedure of `07-preview-and-render-parity.md` §2.2, recorded twice in separate sessions plus once at k·S, stored privately with only their hashes public.

#### Scenario: Stale frame rejected
Given a Save Render image older than the last settings change
When current-frame verification runs
Then the reference MUST be rejected and not admitted to the store

### Requirement: Exception Proposals With Defect Detection
Each exception proposal SHALL name the fixture class, metrics, bounds derived from the measured noise floor and every `uncontrolled` setting it relies on, and its bounds MUST fail a missing channel, a wrong lobe, a roughness offset and a wrong environment rotation.

#### Scenario: Bound too loose
Given a proposed bound that still passes a render with the environment rotated by 90 degrees
When the defect-detection test runs
Then the proposal MUST be rejected before it reaches the owner

### Requirement: Unapproved Or Structural Differences Never Pass
A comparison without an owner-approved register entry MUST be reported `blocked`, and a structural difference (wrong material binding, missing map, wrong geometry, camera or environment) MUST fail regardless of any metric.

#### Scenario: Missing map
Given a production render where the roughness map is not bound
When the Tier 3 report is produced
Then that fixture MUST be reported failed as a structural difference even if its statistics fall within a proposed bound

### Requirement: Cross-Backend Render Report
The report SHALL compare DXR and Vulkan renders of the same fixtures and list every difference; a cross-backend bound MUST exist only as an owner-approved entry.

#### Scenario: Backends differ
Given DXR and Vulkan renders of the white-furnace fixture that differ in some pixels
When the cross-backend report is produced
Then every differing pixel count and statistic MUST be listed and the pair MUST be `blocked` unless an approved entry covers it
