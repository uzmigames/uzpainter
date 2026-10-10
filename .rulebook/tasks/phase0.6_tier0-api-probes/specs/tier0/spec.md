## ADDED Requirements

### Requirement: API readback probes recorded
The Tier 0 API probes MUST record, through documented symbols only, the set→get readback of each property the Phase 1 facade subset uses through a freshly resolved handle and after save and reopen, each recorded at least twice and stored privately.

#### Scenario: Readback after reopen recorded
Given a probe that sets a fill layer property and saves the project
When the project is reopened and the property is read through a freshly resolved handle
Then the readback is recorded as a private golden with its hash in `parity/manifests/phase0/tier0-api-probes.json`

### Requirement: Output-changing quirks captured
The probes MUST capture the active-channel reset after `set_source`, the mask-stack `None` rules, the `EditionContextException` raised by `set_source(None, …)` on a multichannel fill, the `insert_*` position errors and the lifecycle event order.

#### Scenario: Exception recorded with class
Given a multichannel fill layer
When the probe calls `set_source(None, …)` on it
Then the recorded golden holds the raised exception class `EditionContextException`

#### Scenario: Event order recorded
Given a new project created by the probe
When the recorder logs the dispatched events
Then the golden holds the order with `ProjectEditionEntered` after `ProjectCreated`
