## ADDED Requirements

### Requirement: One Build Identity For Release Evidence
The release parity record SHALL name one build hash and dependency lock, and every child result, the budget re-confirmation and the packaging verification MUST name the same pair; any mismatch MUST fail the record.

#### Scenario: Child measured on another build
Given the tier report names build hash H and the conformance result names build hash H2
When the build identity check runs
Then the release parity record fails and names both results

### Requirement: Budgets Re-confirmed On The Frozen Build
The performance measurements SHALL be re-run on the frozen build hash and compared with the published budgets before the release parity record is accepted.

#### Scenario: Budget re-confirmation
Given published budgets measured during tuning and the frozen build hash H
When the measurements are re-run on H
Then the record lists the re-confirmed values next to the published budgets

### Requirement: Integration Closes Only With Every Child Passing
P5-REPORT SHALL be accepted only when the tier report, the Python-disabled conformance result and the capability gap register all pass: Tiers 0–2 equal or covered by approved exceptions, Tier 3 passed only through approved exceptions, every matrix row conforming, and every in-scope gap covered by an owner scope decision.

#### Scenario: Blocked Tier 3 comparison
Given every child passes except one Tier 3 fixture reported blocked for lack of an approved entry
When the integration check runs
Then P5-REPORT is not accepted and the blocked fixture is named

### Requirement: Late Change Reopens The Report
Any change to the build or dependency lock after the freeze MUST reopen this task and `phase5.2_packaging` against the new build.

#### Scenario: Dependency lock updated
Given an accepted release parity record for lock L
When a dependency is updated and the lock becomes L2
Then the record is marked reopened and both P5-REPORT and P5-PACKAGE must pass again on the new build
