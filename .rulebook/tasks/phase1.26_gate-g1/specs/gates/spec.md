## ADDED Requirements

### Requirement: Gate G1 Foundation green
Gate G1 SHALL close only when G0 and every joined item (P1-WAND, P1-STORE, P1-MESH) are accepted and the gate record evidences each G1 clause of `docs/roadmap.md`: Wand v1 maps equal to the private Painter goldens and byte-stable across two runs; the three pipeline scripts running unchanged through the adapter; save/reopen/revert verified with fault injection including commit-then-die retry; certificate and reload fixtures passing.

#### Scenario: All clauses evidenced
Given G0 accepted and P1-WAND, P1-STORE and P1-MESH accepted
When the gate record is written
Then each G1 clause names its accepted task, evidence paths and hashes, and G1 is accepted

### Requirement: Gate requires the previous gate
G1 MUST NOT be accepted while G0 is not accepted, and a single work package carrying gate evidence SHALL NOT close G1 by itself.

#### Scenario: G0 still open
Given every Phase 1 item accepted but G0 not accepted
When G1 acceptance is attempted
Then G1 stays open and the gate record names G0 as the missing item

### Requirement: Gate record keeps oracle data private
The G1 gate record MUST contain numbers and hashes only and SHALL be published in `parity/reports/phase1/` together with the regenerated capability manifest hash and the archive of the Phase 1 tasks.

#### Scenario: Gate commit
Given the gate record and regenerated capability manifest
When the repository guard and `uzpainter parity verify` run
Then both pass and no Painter output is present in the repository
