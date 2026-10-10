## 1. Prerequisites
- [x] 1.1 Prerequisites accepted: phase0.2_parity-contract, phase1.1_docmodel-types-manifest

## 2. Implementation
- [x] 2.1 Implement the persistent copy-on-write document and immutable revision snapshots
- [x] 2.2 Implement transactions under the document lock with detached-subtree attachment for composite operations
- [x] 2.3 Implement transaction results enumerating created/modified/removed/hidden ids and imported/skipped resources
- [x] 2.4 Implement the native explicit `Transaction` for atomic multi-call execution
- [x] 2.5 Implement the operation-record type and the canonical `request_hash`
- [x] 2.6 Implement the idempotency/precondition decision function with the five outcomes of `docs/architecture/09-project-file-format.md` §4
- [x] 2.7 Implement scoped name resolution: all matches returned, ambiguity fails before mutation with candidate ids, repeated named operations idempotent

## 3. Tests
- [x] 3.1 Snapshot immutability: a snapshot taken at revision N is unchanged after later mutations
- [x] 3.2 Failed mutation: the document is unchanged, the revision does not advance and no operation record is produced
- [x] 3.3 Composite failure: nothing is attached and the result lists what would have changed
- [x] 3.4 `Transaction` raising mid-way: none of its calls is applied
- [x] 3.5 Idempotency decision table: one test per branch (stored outcome with newer revision, `idempotency_conflict`, `outcome_unknown` for missing and for expired precondition, `stale_revision`, execute)
- [x] 3.6 `request_hash` is independent of argument key order
- [x] 3.7 LAY-06: ambiguous-name test, repeated-operation test (no duplicate node), save/reopen of ids via manifest round trip

## 4. Acceptance
- [x] 4.1 All tests of this child green on the hosted CPU lane

## 5. Tail (docs + tests — check or waive with tailWaiver)
- [x] 5.1 Update or create documentation covering the implementation
- [x] 5.2 Write tests covering the new behavior
- [x] 5.3 Run tests and confirm they pass
