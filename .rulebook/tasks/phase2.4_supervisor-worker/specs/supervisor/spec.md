## ADDED Requirements

### Requirement: Supervisor Settling Evidence
The runtime SHALL pass every settling case of `docs/architecture/02-runtime-topology.md` §7 on DX12, and every case that needs no GPU device on Vulkan, and each case MUST assert that the MCP session stays alive, the last committed revision is correct and no commit is duplicated.

#### Scenario: Commit-then-die retry
Given a worker that committed a mutation durably and was killed before acknowledging it
When the client retries the same request and then a changed request with the same key
Then the first retry returns the stored outcome with no second revision and the second returns `idempotency_conflict`

#### Scenario: Unwrapped script failure keeps earlier calls
Given a script whose third API call raises after two committed calls
When the script runs through the worker
Then the two earlier calls stay committed and the error receipt reports the last committed revision and the partial changes

### Requirement: Recovery And Overhead Are Measured
The supervisor settling report MUST record the recovery time of every fault case and the per-call overhead against the single-process `run` path for the same command corpus on each backend.

#### Scenario: Settling report produced
Given the settling suite has run on DX12 and Vulkan
And the Vulkan cases that need a Vulkan device are recorded `pending` until `phase3.1_vulkan-compute-parity` settles them (decision 221)
When the report is written to `parity/reports/phase2/supervisor-settling.json`
Then it lists every case and backend as `pass`, `fail` or `pending`, with recovery time and per-call overhead for each case that ran, and contains no oracle data
And every `pending` entry is a Vulkan case that needs a Vulkan device, names decision 121 as its deferral, and is owned by `phase3.1_vulkan-compute-parity` items 3.4 and 4.1 under the decision 221 split
