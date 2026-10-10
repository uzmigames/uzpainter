## ADDED Requirements

### Requirement: G3 Joins Every Mandatory Phase 3 Item
Gate G3 MUST close only when G2 and every mandatory Phase 3 item — P3-BRACERS, P3-UZE, P3-UNREAL, P3-PATHTRACER, P3-CUTOVER and, through them, P3-BAKER, P3-PROC, P3-SMART and P3-VULKAN — are accepted; no single work package SHALL close it.

#### Scenario: One joined item open
Given every Phase 3 item is accepted except `phase3.1_assets3d-cutover`
When the G3 acceptance item is evaluated
Then G3 stays open

### Requirement: G3 Criteria Evidenced
The G3 gate record SHALL reference evidence for every roadmap criterion: Tier 2a/2b per asset and map, bracer r9 Tier 1 equality, Vulkan equal to DX12 on the Tier 0 subset and pilot maps, the Tier 3 report with noise floor and exception proposals, the DXR/Vulkan path-tracer comparison, the UzEngine, Unreal and glTF consumer fixtures and the signed Assets3D amendment.

#### Scenario: Missing Vulkan equality evidence
Given the gate record has no report showing Vulkan outputs equal to DX12 on the pilot maps
When the gate is reviewed
Then G3 is not signed

### Requirement: Tier 3 Passes Only Through Owner Exceptions At G3
G3 MUST NOT record a Tier 3 pass unless an owner-approved entry in the exception register covers it; without one, the Tier 3 report is present and Tier 3 stays blocked.

#### Scenario: Tier 3 report without approved entries
Given a Tier 3 report with exception proposals the owner has not approved
When G3 is evaluated
Then the gate record lists Tier 3 as reported and blocked, not passed

### Requirement: G3 Not-Migratable Settling Check
G3 MUST fail if any gate fixture is marked `not_migratable` without an explicit owner scope decision recorded in the capability manifest and the gate record.

#### Scenario: Hat v5 not migratable without decision
Given hat v5 marked `not_migratable` and no owner scope decision recorded
When G3 is evaluated
Then G3 fails even though bracer r9 passes

### Requirement: G3 Gate Record
The G3 gate record SHALL be written to `parity/reports/phase3/gate-g3.md` with numbers and hashes only, the exceptions relied on, the regenerated capability manifest version, revised duration Hypotheses and the owner's signature.

#### Scenario: Record contains no oracle bytes
Given the completed gate record
When the repository guard scans it
Then it passes the guard and contains only numbers, hashes and references
