## ADDED Requirements

### Requirement: Approved-source index
The project MUST publish `docs/approved-sources.md` listing every source an implementer may use, with its identifier, category, exact revision or hash for files, licence for code, cleared scope and reviewer, and a quarantine list of every off-limits source and every uncleared historical revision.

#### Scenario: Public specification is admitted
Given the OpenPBR Surface specification is cited by `docs/architecture/07-preview-and-render-parity.md`
When the index is published
Then it contains an entry for that specification with its identifier, category and cleared scope

#### Scenario: Off-limits Adobe file is quarantined
Given `docs/licensing-and-clean-room.md` §2 forbids Painter's shipped shader library and `.py` sources
When the index is published
Then its quarantine list names those sources and no approved entry covers them

### Requirement: Historical analyses cleared by exact revision
A historical analysis under `docs/analysis/` MUST NOT be an implementation input unless an itemised provenance audit admits its exact revision hash in the index with provenance and cleared scope; the sanitisation record SHALL NOT count as a clearance.

#### Scenario: Uncleared analysis stays restricted
Given a `docs/analysis/` file that the audit has not cleared
When an implementer looks it up in the index
Then the file appears on the quarantine list and may not be cited as an implementation input

#### Scenario: Cleared revision is pinned
Given the audit clears one revision of an analysis file
When the file later changes
Then only the audited revision hash is approved and the new revision is uncleared until audited

### Requirement: Architecture cites only approved sources
Every source cited by `docs/architecture/*.md` MUST resolve to an approved entry of the index.

#### Scenario: Citation check passes
Given the published index and the architecture documents
When the citation check runs
Then every cited source matches an approved entry and none matches the quarantine list
