## ADDED Requirements

### Requirement: Full Tier Report On The Frozen Build
The final parity report SHALL compare Tiers 0, 1, 2a, 2b and 3 on DX12 and on Vulkan using the frozen release build, and MUST name the build hash and dependency lock it ran on, which MUST equal those of the packaged distribution.

#### Scenario: Report built for release
Given the frozen release build with hash H and its dependency lock
When the comparison runs locally on the owner's machine (decision 028)
Then `parity/reports/phase5/tiers.json` lists every tier on both backends and records build hash H and the same lock as the packaging verification

### Requirement: Exact Equality For Tiers 0 To 2
Tier 0, 1, 2a and 2b outputs MUST equal the Painter goldens, and Vulkan outputs MUST equal DX12 outputs byte for byte; a non-zero difference SHALL pass only when an owner-approved exception entry covers its domain and metric.

#### Scenario: Unexplained texel difference
Given a hat v8 Roughness map that differs from its golden in one texel and no exception entry for that domain
When the report is generated
Then the map is reported as failing with its max |Δ| and differing texel count, and P5-REPORT is not accepted

### Requirement: Tier 3 Passes Only Through Exceptions
A Tier 3 comparison of `painter_iray` against a converged Iray reference SHALL pass only through an owner-approved exception entry derived from the measured noise floor; without one it MUST be reported blocked, and no entry SHALL cover a structural difference.

#### Scenario: Render fixture without an entry
Given a Tier 3 fixture whose residuals were measured but no approved register entry exists
When the report is generated
Then the fixture is reported blocked, not passed

#### Scenario: Structural difference
Given a Tier 3 fixture covered by an approved entry
When the render uses a wrong material binding
Then the comparison fails regardless of the entry's metric bounds

### Requirement: Separate Results And Public Numbers Only
Every comparison SHALL report oracle stability, UzPainter repeatability and equality to Painter separately, with max, mean and p99 |Δ| and differing counts, and the public report MUST contain numbers and hashes only; difference maps and crops MUST stay in the private store.

#### Scenario: Guard over the published report
Given the generated report and exception register
When the repository guard runs on the hosted CPU lane
Then no file whose hash is in the private store index is found and both files validate against their public schemas

### Requirement: Missing Oracle Never Passes
A comparison whose oracle blob cannot be fetched MUST fail as `oracle_unavailable`.

#### Scenario: Blob absent from the store
Given a manifest naming a golden whose blob is missing from `UZP_PARITY_STORE`
When the comparison runs
Then that comparison fails with `oracle_unavailable`

### Requirement: Exception Register Published And Re-verified
The exception register `parity/exceptions.json` SHALL be published with every entry versioned and linked to its owner decision, and each entry's defect-detection test MUST pass on the frozen build.

#### Scenario: Entry whose bound no longer catches defects
Given an exception entry whose defect-detection test passes an injected wrong lobe on the frozen build
When the register is verified
Then the entry is reported invalid and every comparison relying on it fails

### Requirement: Unmigratable Fixture Blocks Its Gate
A required fixture marked `not_migratable` without an explicit owner scope decision MUST be reported as failing its gate even if every other fixture passes.

#### Scenario: Hat fixture not migratable
Given a Tier 1 fixture marked `not_migratable` and no owner scope decision for it
When the report computes per-gate status
Then the gate that fixture belongs to is reported failing
