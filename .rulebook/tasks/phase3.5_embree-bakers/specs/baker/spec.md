# Baker — P3-BAKER integration

## ADDED Requirements

### Requirement: Baker Parent Closure
The P3-BAKER work package SHALL close only when every mandatory child task (`phase3.1_baker-request-model`, `phase3.2_baker-normal`, `phase3.3_baker-evidence-publication` and the nine remaining per-usage baker tasks) has passed its own acceptance.

#### Scenario: One child still open
Given every baker child is accepted except `phase3.4_baker-thickness`
When the parent acceptance is evaluated
Then `phase3.5_embree-bakers` MUST stay open and name the missing child

### Requirement: Tier 2b Report Published
The system MUST publish a Tier 2b report covering the ten `MeshMapUsage` bakers on the analytic fixtures and the wand and hat low/high/cage pairs, comparing hit/coverage evidence before maps, recording the Painter CPU backend of every golden, and passing a map only on exact equality or an owner-approved exception.

#### Scenario: Equal maps across thread counts
Given the Painter CPU goldens for the bevelled cube with highs are in the private store
When the Tier 2b suite bakes all ten usages at two thread counts on the owner's machine
Then every map MUST equal its golden or cite an approved entry of `parity/exceptions.json`, and the report under `parity/reports/phase3/` MUST contain numbers and hashes only

#### Scenario: Unapproved difference
Given a baked AO map differs from its golden in one texel and no exception covers it
When the Tier 2b report is produced
Then the AO map MUST be reported as failed with its max |Δ| and affected-texel count, and the parent acceptance MUST NOT pass

### Requirement: Native Bake Cancellation Through MCP
The system SHALL let an MCP client cancel a native bake; the job MUST reach the `cancelled` terminal state and its receipt MUST state whether work stopped before or after publication, with no partial authoritative bake bound.

#### Scenario: Cancel mid-bake
Given a native bake was started with `bake_start` on a synthetic project with Python disabled
When the client calls `job_cancel` before the bake finishes
Then `job_status` MUST report `cancelled`, the receipt MUST say "stopped before publication", and the mesh-map bindings of the texture set MUST be unchanged
