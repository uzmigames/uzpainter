## ADDED Requirements

### Requirement: Session-separated Iray references
Each analytic fixture MUST have two converged Iray references recorded in separate Painter sessions and one recorded at k·S samples, all through the qualified procedure, stored privately with only their hashes in `parity/manifests/phase0/iray-references.json`.

#### Scenario: Single-session reference is not admitted
Given a fixture with two references recorded in the same Painter session
When admission is checked
Then the fixture is not admitted until a reference from a separate session exists

#### Scenario: Hashes resolve in the store
Given the admitted reference manifest
When `uzpainter parity verify` runs on the owner's machine
Then every listed reference resolves and matches its hash

### Requirement: Iray-side noise terms published
For every admitted fixture the package MUST publish, as numbers only and per material region, the run-to-run difference between the session-separated references and Iray's Monte-Carlo error at S estimated against the k·S reference.

#### Scenario: Repeatable Iray reports zero run-to-run difference
Given two session-separated references that are bit-identical
When the noise terms are computed
Then the run-to-run difference is reported as zero for that fixture

### Requirement: Analytic profile proposed, not assumed
The analytic fixture values MUST be recorded as a proposal to the owner and labelled proposed until the owner ratifies them.

#### Scenario: Report labels the profile
Given the references recorded with the proposed profile
When the report is published
Then it labels the profile values as proposed for ratification
