## ADDED Requirements

### Requirement: Project store settling evidence
The project store SHALL pass every settling-evidence test of `docs/architecture/09-project-file-format.md` §7 before gate G1 can accept it.

#### Scenario: Full §7 run
Given all four children of `phase1.8_project-store` are accepted
When the §7 suite runs end to end
Then every interruption, corruption, replay, revert and plane-isolation test passes and the results are recorded for G1

### Requirement: No duplicate mutation after a crash
A mutation whose commit was durable MUST NOT be applied a second time by any retry, and a retry with the same key and different arguments SHALL be rejected with `idempotency_conflict`.

#### Scenario: Commit then die
Given a mutation committed durably and the process killed before the result was returned
When the same request is retried with the same idempotency key
Then the stored outcome is returned and the project still has exactly one new revision

### Requirement: Recovery preserves content exactly
After any injected interruption the reopened project MUST hold either the previous or the new committed state, with manifests and raster contents byte-identical to that state.

#### Scenario: Interrupted compaction
Given a project interrupted during `VACUUM INTO`
When it is reopened
Then its manifests and pixels equal the state before the compaction
