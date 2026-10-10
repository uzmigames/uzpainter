## ADDED Requirements

### Requirement: Content-addressed private store
The private oracle store MUST address every recorded oracle by SHA-256 in the folder named by `UZP_PARITY_STORE` on the owner's machine, keep records immutable per Painter build, and never upload them to a hosted service.

#### Scenario: Record and fetch by hash
Given an authored sample recorded with `uzpainter parity record`
When `uzpainter parity fetch` resolves its manifest after the local copy is removed
Then the fetched bytes hash to the manifest's SHA-256

#### Scenario: Overwrite is refused
Given an existing record in the store
When a different blob is recorded under the same record id
Then the store refuses the write

### Requirement: Missing oracle is reported, not passed
`uzpainter parity verify` and every comparison MUST report `oracle_unavailable` when a manifest names a blob that is absent or unreadable.

#### Scenario: Hosted runner without store
Given a hosted CI runner without `UZP_PARITY_STORE`
When a Tier 0 comparison needs a private blob
Then the result is `oracle_unavailable`

### Requirement: Owner's machine as self-hosted GPU runner
The owner's machine MUST be registered as the self-hosted GPU runner holding the GPU, the licensed Painter 12.1.0 and the store, and it MUST be the only lane that compares against recorded Painter values.

#### Scenario: Oracle lane runs only on the owner's machine
Given the CI configuration
When a job compares against recorded Painter values
Then it is scheduled only on the self-hosted runner of the owner's machine
