## ADDED Requirements

### Requirement: G0 joins every mandatory Phase 0 item
Gate G0 MUST close only when `phase0.1_approved-source-index`, `phase0.8_tier0-goldens`, `phase0.8_toolchain-slice`, `phase0.6_procedural-feasibility`, `phase0.9_render-reference-capture` and `phase0.9_normal-convention-fixture` are accepted, and a work package carrying gate evidence MUST NOT close the gate by itself.

#### Scenario: Missing joined item keeps the gate open
Given every joined item accepted except `phase0.9_normal-convention-fixture`
When G0 is evaluated
Then the gate stays open

#### Scenario: Evidence package cannot close the gate
Given `phase0.8_tier0-goldens` accepted with its evidence
When no gate record has been written and the other joined items are open
Then G0 is not closed

### Requirement: G0 gate record
The gate MUST publish `parity/reports/phase0/gate-g0.md` holding numbers and hashes only, evidencing every G0 clause of `docs/roadmap.md`: approved-source index published; Tier 0 goldens admitted with first semantics fits; vendored render core building standalone; hardware selftest green on the owner's machine; WARP probe completed and reported; feasibility reports published; Iray capture procedure qualified and references admitted with their noise floor.

#### Scenario: WARP unsupported does not block G0
Given a WARP probe report that marks the WARP path unsupported with reasons
When the gate record is evaluated
Then the WARP clause is satisfied by the completed report

#### Scenario: Oracle blob in the repository blocks G0
Given a recorded Painter output committed to the repository
When the guard runs on the gate commit
Then G0 does not close
