## ADDED Requirements

### Requirement: Long Operations Are Jobs With Durable Terminal Status
Every long operation SHALL run as a job with a unique id and MUST end in exactly one durable terminal state among `succeeded`, `failed`, `cancelled` and `interrupted`.

#### Scenario: Wait for an export
Given an open project
When a client starts an export with `wait=true`
Then it receives progress notifications and a terminal receipt carrying the job id and `succeeded` or `failed`

### Requirement: Cancellation States Commit Boundary
A cancelled job's final receipt MUST state whether work stopped before or after its commit.

#### Scenario: Cancel after commit
Given a job whose result was already committed
When the client cancels it
Then the final receipt reports that work stopped after commit and names the committed revision

### Requirement: Interrupted Jobs Are Resolved, Not Replayed
A job interrupted by a worker death MUST be marked `interrupted` and its outcome MUST be resolved from the persisted operation records without re-executing the job.

#### Scenario: Worker killed mid-job
Given a running mutating job
When the worker process is killed
Then the job is marked `interrupted` and, after relaunch, its outcome is reported from the operation rows with no second execution
