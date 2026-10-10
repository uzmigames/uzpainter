## ADDED Requirements

### Requirement: Tier 0 corpus admitted twice-recorded
Every Tier 0 golden MUST be recorded at least twice through the recorder, stored privately by SHA-256 and listed by hash only in `parity/manifests/`.

#### Scenario: Golden with one recording is not admitted
Given a Tier 0 golden with a single recording
When admission is checked
Then the golden is not admitted until a second recording exists

#### Scenario: Hashes verify on the owner's machine
Given the admitted Tier 0 manifests
When `uzpainter parity verify` runs on the owner's machine
Then every listed blob is present and matches its hash

### Requirement: Stability classified and fits published
The Tier 0 package MUST publish an oracle-stability classification for every recorded channel type and the first `parity/semantics/*.json` fits with their public source and residual, as numbers only.

#### Scenario: Fit without residual is rejected
Given a semantics fit entry without a residual
When the Tier 0 acceptance is reviewed
Then the fit is not published until its residual and public source are recorded
