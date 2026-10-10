## ADDED Requirements

### Requirement: Operation record committed with its revision
Each committed mutation SHALL insert its blobs, its revision row and its operation record `{project_uuid, idempotency_key, request_hash, outcome, committed_revision}` in one SQLite transaction; a failed mutation MUST write no row.

#### Scenario: Killed during commit
Given a mutation whose commit is interrupted by killing the process
When the project is reopened
Then the file holds the previous revision and no operation row for that request

### Requirement: Stored outcome on retry
A retry with a known idempotency key and the same request hash SHALL return the stored outcome without mutating, even when the current revision is newer; the same key with a different request hash MUST be rejected with `idempotency_conflict`.

#### Scenario: Changed request with a used key
Given a committed request with key K
When a request with key K and different arguments is submitted
Then it is rejected with `idempotency_conflict` and no revision is created

### Requirement: Content-addressed, verified storage
Resource bytes SHALL be stored unmodified once per SHA-256, and a blob or manifest whose hash does not match MUST be reported as corrupt with the affected nodes.

#### Scenario: Corrupted blob
Given a `.uzp` whose blob bytes were altered
When the project is opened and the blob is read
Then the corruption is reported with the nodes that bind the blob and no altered bytes are used

### Requirement: Format versioning
A reader MUST refuse a newer major `format_version` with an explicit error and SHALL migrate older minors in memory without rewriting the file before the next commit.

#### Scenario: Newer major
Given a file whose `format_version` major is above the reader's
When it is opened
Then opening fails with an explicit version error and the file is unchanged
