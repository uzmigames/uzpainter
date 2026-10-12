## ADDED Requirements

### Requirement: Tier 0 exact for the Phase 1 subset
The evaluator SHALL reproduce every Tier 0 golden owned by the compositor children exactly at the channel's storage precision; a non-zero difference MUST fail unless an owner-approved entry of `parity/exceptions.json` covers it.

#### Scenario: Acceptance run
Given all seven compositor children are accepted and the private Tier 0 goldens are available on the owner's machine (decision 028)
When the union of their Tier 0 sets is evaluated locally on DX12 and compared
Then every map is equal or covered by a registered exception, and the report lists max |Δ| and differing-texel counts per map

### Requirement: Excluded features are explicit gaps
A node kind, source, projection or effect outside the Phase 1 subset MUST raise `NotYetSupported` before any mutation and SHALL be listed as `release-gap` in the capability manifest.

#### Scenario: Triplanar request in Phase 1
Given a fill layer
When its projection is set to `Triplanar`
Then the call raises `NotYetSupported`, the document is unchanged and the capability manifest lists triplanar projection as `release-gap`
