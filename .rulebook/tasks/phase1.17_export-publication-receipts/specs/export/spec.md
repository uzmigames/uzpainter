## ADDED Requirements

### Requirement: Generational atomic publication
Every export SHALL write its files and receipt into a new generation directory, verify them against the plan and publish them by one atomic durable update of `current.json`; a failure at any step MUST leave the previously published generation selected.

#### Scenario: Interrupted before the pointer update
Given an export interrupted after all files and the receipt were written but before `current.json` was renamed
When a consumer reads `current.json`
Then it sees the previous complete generation and `--recover` completes or discards the new one

### Requirement: Fixed-name consumers read one complete generation
A fixed-name consumer SHALL read only through a generation-pinning delivery adapter or under the coordinated publication lock, and MUST consume one complete generation or fail before consumption when a fixed-name copy was interrupted.

#### Scenario: Interrupted fixed-name copy
Given a fixed-name copy interrupted after two of five files
When the fixed-name consumer is invoked immediately through its adapter
Then it consumes one complete generation or fails before reading any file

### Requirement: Complete export receipts
Each export SHALL produce a receipt carrying the revision, generation, profiles, build, resource hashes, plan hash, per-file path, size, SHA-256, format, bit depth, colour space, channel mapping, normal tag and consumer gaps, and the manifest `exportacao` block.

#### Scenario: Receipt validation
Given a completed export of five maps
When its receipt is validated against `receipt.schema.json`
Then it validates and each file's SHA-256 equals the delivered bytes
