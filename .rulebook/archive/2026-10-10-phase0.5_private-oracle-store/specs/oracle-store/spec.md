## ADDED Requirements

### Requirement: Private oracle store integration
The private oracle store MUST serve recorded oracles by SHA-256 on the owner's machine through `uzpainter parity fetch` and `uzpainter parity verify`, and a missing blob MUST be reported as `oracle_unavailable`, never as a pass.

#### Scenario: Round trip on the owner's machine
Given an authored sample recorded with `uzpainter parity record`
When it is fetched by its manifest and verified
Then the fetched bytes hash to the manifest's SHA-256

#### Scenario: Hosted runner has no oracle
Given a hosted CI runner without store access
When a comparison needs a private blob
Then the comparison reports `oracle_unavailable`

### Requirement: Guard keeps oracle data out of the repository
The repository guard MUST reject a file whose hash is in the store index or that fails public-schema validation, and MUST pass independently authored fixture images and expectation JSON.

#### Scenario: Recorded readback is blocked
Given a recorded JSON API readback staged for commit
When the pre-commit guard runs
Then the commit is rejected

#### Scenario: Authored fixture passes
Given an authored fixture image and an authored expectation JSON
When the guard runs
Then both pass
