## ADDED Requirements

### Requirement: Generated capability manifest
The build SHALL generate `capabilities.json` deterministically from the documented-symbol inventory and the UzPainter additions, with one entry per qualified symbol and operation context carrying status `supported`, `desktop-only-omitted` or `release-gap`.

#### Scenario: Repeat generation
Given unchanged inventory and additions
When the generator runs twice
Then both `capabilities.json` files are byte-identical and validate against the schema

### Requirement: Statuses require evidence
A `supported` status MUST reference Tier 0 evidence and a `desktop-only-omitted` status MUST carry its justification; otherwise generation SHALL fail.

#### Scenario: Unsupported claim
Given an inventory entry marked `supported` with no `tier_evidence`
When the generator runs
Then generation fails naming the entry

### Requirement: Documented symbols only
Every entry in the `substance_painter` context SHALL cite the public API documentation anchor that documents it, and the manifest MUST contain no brush-stroke symbol.

#### Scenario: Entry without a documentation anchor
Given an inventory entry in the `substance_painter` context without a documentation anchor in `evidence`
When the generator validates the inventory
Then the entry is rejected and generation fails
