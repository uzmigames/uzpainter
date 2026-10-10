## ADDED Requirements

### Requirement: Content-based repository guard
The repository guard MUST reject any file whose SHA-256 is in the private store index and any JSON data file under `parity/` that fails its public schema, checking content rather than only file signatures, as a pre-commit hook and as a CI check.

#### Scenario: Recorded PNG is blocked
Given a recorded Painter export PNG whose hash is in the store index
When it is staged and the pre-commit guard runs
Then the commit is rejected

#### Scenario: Re-serialised readback is blocked
Given a recorded JSON API readback re-serialised so its hash no longer matches the index
When it is placed under `parity/` and the guard runs
Then the file fails public-schema validation and is rejected

### Requirement: Authored data passes the guard
The guard MUST pass independently authored fixture images and authored expectation JSON that validate against the public schema.

#### Scenario: Authored fixture and expectation pass
Given an authored fixture image and an authored expectation JSON
When the guard runs in CI
Then the job passes
