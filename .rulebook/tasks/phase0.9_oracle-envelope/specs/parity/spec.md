## ADDED Requirements

### Requirement: Every golden records its oracle environment
Every admitted golden MUST carry an environment record: Painter build string, GPU model, driver version, OS build, colour-configuration hash and recorder version, plus the operator id for Iray references. A field that cannot be known for an existing golden MUST be recorded as `unknown`, never guessed.

#### Scenario: New recording carries the envelope
Given a recorder run on the owner's machine
When a golden is admitted to the store
Then its private record holds the environment record and its public manifest holds the record's hash

### Requirement: Envelope scopes oracle-side comparisons only
UzPainter-to-golden comparisons MUST be evaluated against the golden's recorded envelope without consulting the live environment. Oracle re-recordings and oracle-to-golden comparisons whose envelope differs from the golden's MUST end in `out_of_envelope`, which is never `pass` and never `fail`.

#### Scenario: Driver update does not invalidate UzPainter verdicts
Given a golden recorded under driver A
When UzPainter's output is compared on a machine with driver B
Then the comparison runs against the golden and its outcome follows the comparison rules

#### Scenario: Re-recording under a new driver is out of envelope
Given a golden recorded under driver A
When Painter re-records it under driver B and the two recordings are compared
Then the outcome is `out_of_envelope`

### Requirement: Stability study before further calibration
Every Tier 0 golden MUST be recorded five times (two in one session, two after save/reopen, one in a freshly started Painter process) and its self-variance published before any further calibration of a `calibrated` fit. Fresh-process instability MUST be classified apart from save/reopen instability, and for it the same-session recording r1 MUST stay the exact target (decision 032), with no averaging and no tolerance.

#### Scenario: Fresh-process-only instability
Given a golden whose same-session and save/reopen recordings are equal and whose fresh-process recording differs
When the study is analysed
Then the golden is classified fresh-process-unstable, r1 stays its exact target, and its register entry is prepared but left unapproved until the owner approves it

### Requirement: Canary after environment change
After a GPU, driver, OS or Painter update, the 10-golden canary subset MUST be re-recorded and diffed before the corpus is reused for oracle-side work; any non-zero difference MUST re-record the affected goldens under a new envelope while keeping the originals, their r1 targets and their decision 032 records.

#### Scenario: Canary detects a changed target
Given a canary golden whose re-recording under the new envelope differs in one value
When the canary procedure runs
Then that golden is re-recorded under the new envelope and its original recording stays in the store unchanged
