## ADDED Requirements

### Requirement: Release Manifest Shows Every Gap
The capability manifest generated from the frozen release build SHALL list every Painter Python symbol and every UzPainter operation with one of the statuses `supported`, `desktop-only-omitted` or `release-gap`, and MUST show every remaining output-affecting gap explicitly.

#### Scenario: Unimplemented feature present
Given material layering is not implemented in the frozen build
When the manifest is generated
Then its entries carry `status: "release-gap"` and appear in `parity/reports/phase5/capability-gaps.json`

### Requirement: Supported Requires Evidence
An entry SHALL be `supported` only when its `tier_evidence` resolves to a passing Tier 0 comparison in the Phase 5 tier report; a `desktop-only-omitted` entry MUST carry a per-symbol justification that it changes no texture, render or script-visible state.

#### Scenario: Supported entry without evidence
Given an entry marked `supported` whose `tier_evidence` names no passing comparison
When the evidence check runs
Then the check fails and names the entry

### Requirement: Gaps Need An Owner Scope Decision
Every in-scope `release-gap` entry and every required fixture marked `not_migratable` MUST either reference an explicit owner scope decision recorded under `.rulebook/decisions/` or be reported `blocking`; reporting a gap SHALL NOT count as accepting it.

#### Scenario: Gap without a decision
Given arbitrary `.sbsar` evaluation listed as `release-gap` and no owner scope decision for it
When the gap register is written
Then the entry has status `blocking` and P5-REPORT is not accepted

#### Scenario: Gap covered by a decision
Given the owner records a scope decision excluding USD scene export from v1
When the manifest is regenerated
Then the USD entry references that decision id and is not reported `blocking`

### Requirement: Nothing Is Silently A No-Op
A `release-gap` symbol MUST raise `uzpainter.NotYetSupported` before any mutation, and a `desktop-only-omitted` symbol MUST raise `uzpainter.UnsupportedInUzPainter` with its reason and alternative.

#### Scenario: Calling a gap symbol
Given a project at revision R
When a script calls a symbol whose status is `release-gap`
Then `NotYetSupported` is raised and the project stays at revision R

### Requirement: No Full-Replacement Claim While A Gap Is Open
The manifest, release notes and `README.md` MUST NOT call UzPainter a full replacement of Substance Painter while any required gap is open.

#### Scenario: Wording check
Given one in-scope gap still `blocking`
When the wording check scans the release documents
Then any "full replacement" claim is reported and fails the check
