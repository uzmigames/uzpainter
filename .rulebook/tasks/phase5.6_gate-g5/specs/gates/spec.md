## ADDED Requirements

### Requirement: G5 Joins Every Mandatory Phase 5 Item
Gate G5 MUST close only when P5-PERF, P5-PACKAGE, P5-REPORT (with its three children) and P5-HISTORY are accepted and G4 is accepted; no single work package SHALL close it.

#### Scenario: Clean history still open
Given every Phase 5 item is accepted except `phase5.5_clean-history`
When the G5 acceptance item is evaluated
Then G5 stays open and the repository stays private

### Requirement: G5 Release Criteria Evidenced
The G5 gate record SHALL reference evidence for every release criterion: Tiers 0–2 green or covered by approved exceptions, Tier 3 passed only through approved exceptions, Python-disabled conformance for every matrix row, the offline clean-machine run, the size census against the 10 % candidate budget, consumer-validated presets, recovery and fault-injection tests, the publication criteria and the clean-history verification.

#### Scenario: Census missing
Given a gate record without the size census report for the body projects
When the gate is reviewed
Then G5 is not signed

### Requirement: Scope Decisions Not Gap Reports
G5 MUST fail while any in-scope capability is neither `supported` nor covered by an explicit owner scope decision, and while any required fixture is `not_migratable` without such a decision; reporting a gap SHALL NOT count as accepting it.

#### Scenario: Blocking gap at release
Given the gap register lists material layering as `blocking`
When G5 is evaluated
Then the gate fails and names the gap

### Requirement: No Full-Replacement Claim With An Open Gap
The gate record and the release documents MUST NOT call UzPainter a full replacement of Substance Painter while a required gap is open.

#### Scenario: Release notes claim full replacement
Given an open required gap covered only by a scope decision that narrows v1
When the release notes describe v1 as a full replacement
Then the wording check fails and G5 is not signed

### Requirement: One Build Identity At Release
The packaging verification, the final parity report and the clean-history verification MUST name the same build hash, dependency lock and released tree.

#### Scenario: History built from another tree
Given the clean-history record names a tree that differs from the packaged build's tree
When G5 is evaluated
Then the gate fails

### Requirement: Publication Only After Signature And Authorisation
The repository SHALL be made public only after G5 is signed by the owner, `phase5.5_clean-history` has passed and the owner has explicitly authorised publication at execution time.

#### Scenario: Signed gate without publication authorisation
Given G5 signed and the clean history verified
When no explicit owner authorisation to make the repository public is recorded
Then the repository stays private
