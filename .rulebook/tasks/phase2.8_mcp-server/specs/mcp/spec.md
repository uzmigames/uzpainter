## ADDED Requirements

### Requirement: Phase 2 MCP Contract Fixtures Pass
The MCP server SHALL pass the Phase 2 typed-tool, transport, lease, error and retry contract fixtures of `docs/architecture/11-mcp-server.md` §7 on synthetic project and job fixtures.

#### Scenario: Worker dies between commit and acknowledgement
Given a mutating MCP call whose worker commits durably and is killed before the supervisor acknowledges
When the client retries the same request and then a changed request with the same key
Then the first retry returns the stored outcome without a second revision and the second returns `idempotency_conflict`

#### Scenario: HTTP reconnect
Given a resident server in HTTP mode with a running job
When the client disconnects and reconnects with its token
Then it can query the job by id and its lease state is unchanged

### Requirement: Later Families Reported As Gaps
Operation families not implemented in Phase 2 MUST be reported as capability gaps, and any operation that still needs Python MUST be shown as a gap in the capability resource.

#### Scenario: Capabilities read in Phase 2
Given the Phase 2 build
When a client reads `uzpainter://capabilities`
Then native bake, procedural families, later node kinds and `painter_iray` appear as capability gaps
