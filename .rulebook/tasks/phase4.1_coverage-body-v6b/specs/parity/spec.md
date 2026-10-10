## ADDED Requirements

### Requirement: Body v6b Tier 1 Equality Across Three Sets
Body v6b rebuilt in UzPainter with three 4096² texture sets in one project MUST export every map equal to the private Painter goldens at native depth, before and after save/reopen; a difference passes only through an owner-approved exception.

#### Scenario: Equal after reopen
Given body v6b rebuilt and saved
When the project is closed, reopened and exported again
Then every map of the three sets equals the private goldens and the first export byte for byte

### Requirement: Body v6b Memory Admission
Evaluation of body v6b SHALL stay within the VRAM tile budget derived at startup, evaluating the three sets in sequence, and a texture-set creation above the budget MUST fail explicitly.

#### Scenario: Over-budget set refused
Given the body project with three 4096² sets and a measured budget that cannot hold a fourth
When a fourth 4096² set is created
Then creation fails with an explicit budget error and the project is unchanged

### Requirement: Body v6b Size Census
The body v6b census SHALL report project bytes, external dependency bytes and retained history against the matched `.spp` after Painter's documented compact-save, with linked bytes counted on both sides, and SHALL state the ratio against the 10 % candidate budget.

#### Scenario: Census published
Given the rebuilt body v6b project with Q11 retention applied
When the census runs
Then `parity/reports/phase4/` lists both sides' byte counts and the ratio to the matched `.spp`

### Requirement: Body v6b Budgets Measured
Timing and peak memory for evaluation, export, save, reopen and compaction of body v6b SHALL be measured and published for P5-PERF.

#### Scenario: Budgets recorded
Given a complete body v6b run locally on the owner's machine (decision 028)
When the run finishes
Then the report lists each operation's time and peak RAM and VRAM with the build hash
