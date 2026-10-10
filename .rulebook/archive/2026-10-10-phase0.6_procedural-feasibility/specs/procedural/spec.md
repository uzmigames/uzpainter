## ADDED Requirements

### Requirement: Procedural residuals published
The procedural feasibility study MUST publish, as numbers only, the residuals of two mesh-map generator prototypes and the Leather Damaged prototype against private Painter oracles on the sphere and bevelled-cube fixtures, with max, mean and p99 absolute difference and affected-texel counts.

#### Scenario: Residual report lists every case
Given prototype outputs and twice-recorded oracles for each asset and fixture
When the comparison runs on the owner's machine
Then the report lists max, mean and p99 absolute difference and the affected-texel count for every case

#### Scenario: Non-zero residual is not a pass
Given a prototype with a non-zero residual
When the report classifies it
Then it is reported as a candidate exception or gap, never as equal

### Requirement: Go/no-go for Phase 3 scope
The report MUST state a go or no-go per procedural family for the Phase 3 procedural package, derived from the measured residuals.

#### Scenario: Decision per family
Given the published residuals
When the feasibility report is reviewed
Then each evaluated family carries a go or no-go with its supporting numbers

### Requirement: Clean-room provenance of procedural prototypes
Each prototype formula MUST cite a public source, and observed Painter preset structures and outputs MUST stay in the private store.

#### Scenario: Observed structure is not committed
Given the readback of the Leather Damaged preset structure
When the guard runs on the repository
Then the readback is absent from the repository and only its hash is public
