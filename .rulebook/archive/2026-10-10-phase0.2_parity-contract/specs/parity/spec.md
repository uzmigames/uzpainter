## ADDED Requirements

### Requirement: Exact-equality parity contract
`parity/CONTRACT.md` MUST state that every comparison passes only on exact equality of native decoded values, that any non-zero difference passes only through an owner-approved, versioned exception in the register, that no preset tolerance exists, and that diagnostic metrics never grant an exception.

#### Scenario: Explained difference without exception fails
Given a Tier 1 map that differs from the Painter golden in one texel with a documented explanation
When the comparison is evaluated under the contract
Then the result is a failure because no register entry covers it

#### Scenario: Missing oracle blob is not a pass
Given a public manifest whose private oracle blob is unavailable
When the comparison runs
Then the result is `oracle_unavailable` and the comparison does not pass

### Requirement: Public and private golden schemas
The repository MUST provide `parity/schema/golden-public.json` for independently authored inputs, applied settings, public-documentation-derived expectations, software identities and SHA-256 hashes of private records, and `parity/schema/golden-private.json` for every recorded Painter output; no recorded output SHALL validate against the public schema.

#### Scenario: Public sample validates
Given an authored public manifest sample
When it is validated against `golden-public.json`
Then validation succeeds

#### Scenario: Recorded readback is rejected by the public schema
Given a private-shaped JSON API readback record
When it is validated against `golden-public.json`
Then validation fails

### Requirement: Exception register schema
The repository MUST provide `parity/schema/exceptions.json` and a register `parity/exceptions.json` whose entries record domain, metric and bound, evidence, every `uncontrolled` setting relied on, a defect-detection test, the approving decision id and a version.

#### Scenario: Incomplete exception entry is rejected
Given an exception entry without a defect-detection test
When it is validated against `parity/schema/exceptions.json`
Then validation fails

### Requirement: Comparison-tool specification
The contract MUST specify the diagnostics reported with every comparison (max, mean and p99 absolute difference, differing-texel count and percentage, per-region breakdown, normal angular statistics, exact ID and alpha checks, the Tier 3 statistics) and that FLIP is a pinned diagnostic only.

#### Scenario: Mean alone is never reported
Given a comparison report for a map
When it lists a mean or percentile difference
Then the maximum difference and the affected-texel count are listed next to it
