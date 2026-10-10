# Baker — evidence, receipts, publication and jobs

## ADDED Requirements

### Requirement: Evidence Maps Never Alter The Compatible Map
Every bake SHALL produce the compatible map plus `raw`, `hit`, `coverage`, `miss` and `extension` evidence maps stored under `cache/`; the evidence MUST NOT change any texel of the compatible map.

#### Scenario: Evidence regenerated
Given a published bake whose `cache/` evidence was deleted
When the evidence is regenerated from the same request and input revision
Then the evidence maps MUST be byte-identical to the originals and the compatible map MUST be unchanged

### Requirement: Receipt Surface Accounting And Conservation
Every bake MUST write a `BakeReceipt` with the fields of `06-baking.md` §4; the seven used-surface classes MUST be disjoint and sum to `coverage.conservative_texels`, and the test MUST assert exact per-class counts on analytic fixtures, not only schema validity.

#### Scenario: Buried-face fixture
Given the analytic fixture with a part that has a buried face and its independently authored expected counts
When the bake runs
Then each used-surface class count MUST equal the expected count and the classes MUST sum to `coverage.conservative_texels`

#### Scenario: No silent repair
Given a request without an enabled fallback
When texels miss the high-poly mesh
Then `fallback_texels` and `repaired` MUST be zero and the missed texels MUST be counted as `miss`

### Requirement: Atomic Bake Publication
Publication SHALL be atomic per `(texture set, input revision)`: either all enabled usages are bound with `baked {…}` provenance and the receipt stored with them, or nothing is bound.

#### Scenario: One baker fails
Given a bake of `Normal` and `AO` where the `AO` baker fails
When the job ends
Then the job status MUST be `Fail` with per-baker detail and neither map MUST be bound as authoritative

### Requirement: Bake Jobs And Facade Events
Bakes SHALL run as jobs with unique ids, progress, `cancel()` and one terminal status `Success | Cancel | Fail`; `bake_async` MUST return a `StopSource`, events `BakingProcessAboutToStart`, `BakingProcessProgress` and `BakingProcessEnded` MUST be dispatched on the Python dispatcher thread, and `project.is_busy()` MUST be true while the job runs.

#### Scenario: Event order
Given a script subscribed to the three baking events
When it calls `bake_async(texture_set)` and the bake succeeds
Then it MUST receive `BakingProcessAboutToStart`, then progress events, then `BakingProcessEnded(Success)`, all on the dispatcher thread

### Requirement: MCP Native Bake Cancellation
`bake_start` and `job_cancel` SHALL let an MCP client cancel a native bake; cancellation MUST be acknowledged immediately and the receipt MUST state whether work stopped before or after publication.

#### Scenario: Cancel after publication
Given a bake whose publication already committed
When the client calls `job_cancel`
Then the receipt MUST say "stopped after publication" and the committed bindings MUST remain intact
