## ADDED Requirements

### Requirement: Single Writer Per Project
The supervisor SHALL hold one mutation lease per open project and MUST reject a mutating call from a client without the lease with `lease_held {holder, since, active_job}`; reads MUST NOT require the lease.

#### Scenario: Second writer
Given client A holds the lease of an open project
When client B sends a mutating call for that project
Then B receives `lease_held` naming A and the active job, and no revision is committed

### Requirement: Retries Never Duplicate A Committed Mutation
A retry with a known idempotency key and the same request hash MUST return the stored outcome without mutating, even when the current revision is newer, and the same key with a different request hash MUST be rejected with `idempotency_conflict`.

#### Scenario: Lost acknowledgement
Given a mutation committed durably and the worker killed before the supervisor acknowledged it
When the client retries the same request with the same key and precondition
Then the stored outcome is returned and no second revision exists

#### Scenario: Key reused with other arguments
Given a committed mutation with key K
When a request with key K and different arguments arrives
Then the call returns `idempotency_conflict {key, committed_revision}` and nothing is mutated

### Requirement: Unknown Keys Follow The Precondition Rule
An unknown key with a missing or expired original precondition MUST return `outcome_unknown` with the current revision and MUST NOT execute; an unknown key with an unexpired precondition SHALL execute only when that precondition equals the current revision and otherwise MUST return `stale_revision`.

#### Scenario: Replay after retention, compaction and ledger loss
Given a non-idempotent mutation whose operation row was pruned by compaction and a deleted supervisor ledger
When the original key is replayed with its original precondition and again with no precondition
Then both replays return `outcome_unknown` or `stale_revision` and neither creates a mutation

### Requirement: Ledger Reconciled Before Admission
After a worker restart the supervisor MUST reconcile its ledger from the project store's operation rows newer than its last acknowledged revision before admitting any call for that project.

#### Scenario: Restart with an unacknowledged commit
Given the worker committed revision N and died before acknowledgement
When the relaunched worker reconnects
Then the supervisor records revision N's outcome from the operation row before it admits the next call
