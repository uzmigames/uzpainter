## ADDED Requirements

### Requirement: UI-only Tier 0 cases are recorded with a verified settings sheet
The Tier 0 corpus MUST contain goldens for both height→normal project-setting methods, a height→normal strength sweep for each method, and a group in `PassThrough` mode with masks on the group and on a child. Every value set through Painter's UI (decision 029) SHALL be named in the public manifest's `applied_settings` with `applied_by: operator_settings_sheet`, and MUST be verified and recorded privately.

#### Scenario: Strength sweep recorded per method
Given the authored height ramps
When the corpus is recorded
Then for each height→normal method there are goldens at the default strength and at least three other strengths, each recorded twice

#### Scenario: A UI value that differs from the sheet is refused
Given an operator settings sheet with a strength value
When the value Painter shows differs from the sheet
Then the recorder refuses the golden and writes nothing

### Requirement: Blobs private, hashes public
Recorded outputs, UI screenshots and readbacks MUST be stored only in the private store; the public manifests SHALL hold only authored inputs, instruction sequences, settings-sheet names and values, software identities and SHA-256 hashes.

#### Scenario: Verify round trip
Given the public manifests and the owner's private store
When `uzpainter parity verify` runs
Then every listed hash resolves to a stored blob with a matching digest
