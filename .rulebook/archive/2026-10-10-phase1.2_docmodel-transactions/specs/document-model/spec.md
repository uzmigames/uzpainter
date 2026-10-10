## ADDED Requirements

### Requirement: Transactions produce immutable revisions
Each committed call SHALL be one transaction producing a new immutable revision; a failed call MUST leave the document and revision unchanged and produce no operation record.

#### Scenario: Failed call
Given a document at revision 7
When a mutation fails validation
Then the document is unchanged, the revision is still 7 and no operation record exists for that call

### Requirement: Idempotency and precondition decision
The operation-record contract MUST decide every mutation request as stored outcome, `idempotency_conflict`, `outcome_unknown`, `stale_revision` or execute, exactly as `docs/architecture/09-project-file-format.md` §4 specifies, checking a known key before the current revision.

#### Scenario: Known key after the revision advanced
Given a committed request with key K at revision 5 and a current revision 9
When the same request with key K is retried
Then the stored outcome is returned and no new revision is created

#### Scenario: Reused key with different arguments
Given a committed request with key K
When a request with key K and different arguments arrives
Then it is rejected with `idempotency_conflict`

### Requirement: Scoped, idempotent name addressing
Name-addressed mutations SHALL resolve within an explicit `{project, set, stack, parent}` scope; an ambiguous match MUST fail before mutation listing the candidate ids, and repeating the same named operation SHALL create no duplicate node.

#### Scenario: Repeated named insert
Given a named fill layer already inserted under a group
When the same named insert is executed again in the same scope
Then no second node is created and the result names the existing node
