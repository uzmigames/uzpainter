## ADDED Requirements

### Requirement: G4 Joins Every Mandatory Phase 4 Item
Gate G4 MUST close only when G3 and every mandatory Phase 4 item — P4-HAT8, P4-BODY, P4-NODES, P4-TILES and their child tasks — are accepted; no single work package SHALL close it, and the optional P4-DXR SHALL neither block nor satisfy it.

#### Scenario: One joined item open
Given every Phase 4 item is accepted except `phase4.5_uv-tiles`
When the G4 acceptance item is evaluated
Then G4 stays open

#### Scenario: Optional GPU baker not delivered
Given every mandatory Phase 4 item is accepted and `phase4.3_dxr-baker` is not delivered
When the G4 acceptance item is evaluated
Then G4 can close and the gate record states the GPU baker as not delivered

### Requirement: G4 Criteria Evidenced
The G4 gate record SHALL reference evidence for every roadmap criterion: hat v8 and body v6b Tier 1 equality, UV tiles Tier 0/1 on a UDIM fixture, the Tier 0 corpus extended to the new node kinds, and a capability manifest that lists every remaining gap explicitly.

#### Scenario: Missing body v6b evidence
Given the gate record has no Tier 1 report for one of the three body v6b sets
When the gate is reviewed
Then G4 is not signed

### Requirement: Remaining Gaps Explicit At G4
The capability manifest regenerated at G4 MUST list every remaining gap explicitly, including arbitrary `.sbsar`, auto-unwrap, material layering and the deferred export formats, and SHALL NOT present a gap as supported.

#### Scenario: Auto-unwrap still a gap
Given auto-unwrap has no implementation
When the G4 capability manifest is regenerated
Then auto-unwrap is listed as `release-gap` and the gate record lists it

### Requirement: G4 Not-Migratable Settling Check
G4 MUST fail if any gate fixture of P4-HAT8 or P4-BODY is marked `not_migratable` without an explicit owner scope decision recorded in the capability manifest and the gate record.

#### Scenario: Hat v8 layer not migratable without decision
Given a hat v8 paint layer marked `not_migratable` and no owner scope decision recorded
When G4 is evaluated
Then G4 fails even though body v6b and the UDIM fixture pass

### Requirement: G4 Gate Record
The G4 gate record SHALL be written to `parity/reports/phase4/gate-g4.md` with numbers and hashes only, the exceptions relied on, the regenerated capability manifest version, the revised Phase 5 duration Hypothesis and the owner's signature.

#### Scenario: Record contains no oracle bytes
Given the completed gate record
When the repository guard scans it
Then it passes the guard and contains only numbers, hashes and references
