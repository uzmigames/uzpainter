## ADDED Requirements

### Requirement: Documented-API-only recording
The recorder MUST read and change Painter state only through symbols documented in Painter's public `python-doc`, and MUST NOT use the community MCP bridge or any private or inferred interface.

#### Scenario: Private attribute is rejected
Given a recorder change that accesses an undocumented underscore attribute of a `substance_painter` object
When the provenance test runs
Then the test fails and names the undocumented symbol

#### Scenario: Bridge import is rejected
Given a recorder module that imports the community MCP bridge
When the provenance test runs
Then the test fails

### Requirement: Qualified pixel capture with current-frame verification
The recorder MUST capture pixels only through `export_project_textures` or the Iray procedure of `07-preview-and-render-parity.md` §2.2, and MUST verify readiness and that the captured output postdates the last settings change.

#### Scenario: Stale export is refused
Given an export file whose timestamp predates the last applied instruction
When the recorder verifies the capture
Then the record is refused and no golden is written

### Requirement: Private records and public hashes
Every recorded Painter output MUST be written as a private record per `parity/schema/golden-private.json` outside the repository, and only its SHA-256 MAY appear in the public manifest.

#### Scenario: Recorded export stays private
Given a recorded 16-bit export
When the recorder finishes
Then the PNG exists only in the private output directory and the public manifest holds its SHA-256

### Requirement: Every golden recorded twice
The recorder MUST record each golden at least twice, in the same session and after save and reopen.

#### Scenario: End-to-end Tier 0 sample
Given an authored Tier 0 fixture and its instruction sequence
When the recorder runs on the owner's machine
Then two records exist, both validate against the private schema and the public manifest lists both hashes
